"""Local CFD YOLO detection and BoT-SORT tracking; coordinates use original pixels."""
import argparse, csv, json, time
from pathlib import Path
import cv2
import torch
from ultralytics.utils import YAML
from ultralytics.utils.checks import check_yaml
from fish_settings import read_settings
from enhancement import correct_frame
from detectors import build_detector
from fish_similarity import CropSampler

p = argparse.ArgumentParser()
p.add_argument('--source', required=True)
p.add_argument('--output', default='outputs/full')
p.add_argument('--limit', type=int, default=0)
p.add_argument('--device', default='cuda:0')
p.add_argument('--batch', type=int, default=8)
p.add_argument('--settings')
a = p.parse_args()
settings=read_settings(a.settings); tracking=settings['tracking']
out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
torch.set_num_threads(4)
if a.device == 'mps' and not torch.backends.mps.is_available():
    raise RuntimeError('Metal GPU is unavailable in this process. Run with local GPU access, or explicitly choose --device cpu.')
cap = cv2.VideoCapture(a.source)
if not cap.isOpened(): raise RuntimeError('Cannot open the selected video.')
fps = cap.get(cv2.CAP_PROP_FPS)
if fps <= 0: raise RuntimeError('The video has no valid frame rate.')
width, height = (int(cap.get(x)) for x in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT))
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
tracker_config=YAML.load(check_yaml('botsort.yaml'))
for key in ['track_low_thresh','track_high_thresh','new_track_thresh','match_thresh','with_reid','appearance_thresh','proximity_thresh']:tracker_config[key]=tracking[key]
tracker_config['track_buffer']=max(1,round(tracking['gap_seconds']*fps))
tracker_path=out/'tracker.yaml'; YAML.save(tracker_path,tracker_config)
(out/'settings.json').write_text(json.dumps(settings,indent=2))
detector=build_detector(settings,tracker_config,tracker_path,a.device,a.batch)
print('Detector:',detector.model_id,flush=True)
scale = min(1,1920/max(width,height))
ow,oh = (max(2,int(d*scale)//2*2) for d in (width,height))
writer = cv2.VideoWriter(str(out/'annotated_silent.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), fps, (ow,oh))
sampler = CropSampler(out, fps)
tracks = {}; start = time.time(); frame_no = 0; rows = 0
def processed_frames():
    read = 0
    while cap.isOpened():
        batch = []
        for _ in range(detector.batch):
            if a.limit and read >= a.limit: break
            ok, frame = cap.read()
            if not ok: break
            batch.append(frame); read += 1
        if not batch: break
        corrected=[correct_frame(frame,settings['color']) for frame in batch]
        results = detector.track(corrected)
        yield from zip(batch, results)

with (out/'detections.csv').open('w') as f:
    csvout = csv.writer(f)
    csvout.writerow(['frame','time_s','track_id','confidence','x1','y1','x2','y2','class'])
    for frame, result in processed_frames():
        view = cv2.resize(frame, (ow,oh))
        for box in result.boxes:
            xy = box.xyxy[0].cpu().tolist(); confidence = float(box.conf[0])
            ident = int(box.id[0]) if box.id is not None else None
            csvout.writerow([frame_no,round(frame_no/fps,4),ident,round(confidence,5),*[round(x,2) for x in xy],'fish'])
            rows += 1
            if ident is not None:
                t = tracks.setdefault(ident,dict(first_frame=frame_no,last_frame=frame_no,detections=0,best_confidence=0))
                t['last_frame']=frame_no; t['detections']+=1
                sx1,sy1,sx2,sy2 = map(int,xy)
                sampler.add(ident, frame_no, confidence, frame[max(0,sy1):min(height,sy2),max(0,sx1):min(width,sx2)])
                if confidence > t['best_confidence']:
                    t['best_confidence']=confidence
                    x1,y1,x2,y2 = map(int,xy)
                    crop=frame[max(0,y1):min(height,y2),max(0,x1):min(width,x2)]
                    if crop.size: cv2.imwrite(str(out/f'fish_{ident:04d}.jpg'),crop)
            color = (0,200,255) if ident is None else ((ident*53)%200+55,(ident*97)%200+55,(ident*139)%200+55)
            x1,y1,x2,y2 = [int(x*s) for x,s in zip(xy,(ow/width,oh/height,ow/width,oh/height))]
            cv2.rectangle(view,(x1,y1),(x2,y2),color,2)
            label=f'Fish {ident:04d}' if ident is not None else 'Fish pending'
            cv2.putText(view,f'{label} {confidence:.2f}',(x1,max(20,y1-7)),cv2.FONT_HERSHEY_SIMPLEX,.6,color,2)
        cv2.putText(view,f'{frame_no/fps:.1f}s | Track IDs are provisional',(20,35),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2)
        writer.write(view)
        if frame_no in (0,300,900,1800,3000,4500): cv2.imwrite(str(out/f'preview_{frame_no:05d}.jpg'),view)
        frame_no += 1
        if frame_no % 30 == 0:
            f.flush()
            print(f'{frame_no}/{total} frames; {len(tracks)} tracks; {frame_no/(time.time()-start):.2f} fps',flush=True)
cap.release(); writer.release()
with (out/'tracks.csv').open('w') as f:
    c=csv.writer(f); c.writerow(['track_id','first_s','last_s','detections','best_confidence','review_status'])
    for ident,t in sorted(tracks.items()):
        c.writerow([ident,round(t['first_frame']/fps,3),round(t['last_frame']/fps,3),t['detections'],round(t['best_confidence'],4),'unreviewed'])
(out/'run.json').write_text(json.dumps(dict(source=a.source,model=detector.model_id,tracker='BoT-SORT custom settings',settings=settings,imgsz=tracking['imgsz'],confidence=tracking['confidence'],iou=tracking['iou'],device=a.device,batch=detector.batch,half_precision=detector.half_precision,source_fps=fps,width=width,height=height,output_width=ow,output_height=oh,processed_frames=frame_no,total_frames=total,track_count=len(tracks),detection_rows=rows,elapsed_seconds=time.time()-start),indent=2))
print('Complete',flush=True)
