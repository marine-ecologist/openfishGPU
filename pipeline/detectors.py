"""Fish detector adapters with a shared BoT-SORT result format."""
from pathlib import Path
import cv2,numpy as np,torch

class YOLODetector:
    model_id='cfd-yolov12x-1.00'
    half_precision=True
    def __init__(self,settings,tracker_config,tracker_path,device,batch):
        from ultralytics import YOLO
        self.model=YOLO(__import__('os').environ.get('OPENFISH_DETECTOR_MODEL', 'models/cfd-complete.pt'));self.t=settings['tracking'];self.path=str(tracker_path.resolve());self.device=device;self.batch=batch
        if self.t['with_reid']:
            from ultralytics.nn.modules.head import Detect
            head=self.model.model.model[-1]
            if not isinstance(head,Detect) or getattr(head,'end2end',False):raise ValueError('This YOLO detector does not support native appearance matching.')
    def track(self,frames):
        return self.model.track(frames,persist=True,tracker=self.path,conf=self.t['confidence'],iou=self.t['iou'],imgsz=self.t['imgsz'],device=self.device,quantize=32 if str(self.device) == 'cpu' else 16,verbose=False)

class RFDETRDetector:
    model_id='cfd-rf-detr-small-1024-2026.07.06'
    half_precision=False
    batch=1
    def __init__(self,settings,tracker_config,tracker_path,device,batch):
        import rfdetr
        from ultralytics.trackers.bot_sort import BOTSORT
        from ultralytics.utils import IterableSimpleNamespace
        self.t=settings['tracking'];path=Path('models/cfd-rfdetr-small.pth')
        if not path.is_file():raise ValueError('The RF-DETR fish weights are missing from models/.')
        if self.t['with_reid']:raise ValueError('Native appearance matching is currently supported by YOLO only.')
        self.model=rfdetr.from_checkpoint(path,device=device,resolution=self.t['imgsz'])
        args=IterableSimpleNamespace(**tracker_config);args.device=torch.device(device);self.tracker=BOTSORT(args)
    def track(self,frames):
        from ultralytics.engine.results import Boxes,Results
        output=[]
        for frame in frames:
            detected=self.model.predict(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB),threshold=self.t['confidence'],include_source_image=False)
            data=np.zeros((len(detected),6),dtype=np.float32)
            if len(detected):data[:,:4]=detected.xyxy;data[:,4]=detected.confidence
            h,w=frame.shape[:2];data[:,[0,2]]=data[:,[0,2]].clip(0,w);data[:,[1,3]]=data[:,[1,3]].clip(0,h)
            data=data[np.isfinite(data).all(axis=1)&(data[:,2]>data[:,0])&(data[:,3]>data[:,1])]
            tracks=self.tracker.update(Boxes(data,frame.shape[:2]),frame)
            if len(tracks):data=tracks[:,:-1].astype(np.float32)
            elif any(not t.is_activated for t in self.tracker.tracked_stracks):data=np.zeros((0,6),np.float32)
            data[:,[0,2]]=data[:,[0,2]].clip(0,w);data[:,[1,3]]=data[:,[1,3]].clip(0,h)
            data=data[(data[:,2]>data[:,0])&(data[:,3]>data[:,1])]
            output.append(Results(orig_img=frame,path='video-frame',names={0:'fish'},boxes=torch.from_numpy(data)))
        return output

def build_detector(settings,tracker_config,tracker_path,device,batch):
    cls=YOLODetector if settings['detector']['name']=='yolo' else RFDETRDetector
    return cls(settings,tracker_config,tracker_path,device,batch)
