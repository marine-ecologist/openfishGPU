"""Validated, serializable settings shared by the interface and workers."""
import copy,json,math

DEFAULTS={
    'detector':{'name':'yolo'},
    'color':{'enabled':False,'red_gain':1.0,'blue_gain':1.0,'black':0,'white':255,'gamma':1.0,'local_contrast':0.0,'saturation':1.0,'sharpness':0.0},
    'tracking':{'confidence':0.10,'track_low_thresh':0.10,'track_high_thresh':0.25,'new_track_thresh':0.35,'gap_seconds':3.0,'match_thresh':0.8,'iou':0.5,'imgsz':1024,'with_reid':False,'appearance_thresh':0.8,'proximity_thresh':0.5},
}

def normalize_settings(settings=None):
    result=copy.deepcopy(DEFAULTS)
    for section,values in (settings or {}).items():
        if section not in result or not isinstance(values,dict):raise ValueError('Invalid settings section')
        for key,value in values.items():
            if key not in result[section]:raise ValueError(f'Unknown setting: {key}')
            result[section][key]=value
    c,t=result['color'],result['tracking']
    if result['detector']['name'] not in ('yolo','rfdetr'):raise ValueError('Choose YOLO or RF-DETR.')
    if result['detector']['name']=='rfdetr' and t['with_reid']:raise ValueError('Native appearance matching is currently available with YOLO only.')
    bounds={'red_gain':(.5,2.5),'blue_gain':(.5,2.5),'black':(0,254),'white':(1,255),'gamma':(.5,2),'local_contrast':(0,4),'saturation':(.5,1.8),'sharpness':(0,1.5)}
    for key,(lo,hi) in bounds.items():
        if not isinstance(c[key],(int,float)) or not math.isfinite(c[key]) or not lo<=c[key]<=hi:raise ValueError(f'Color {key} must be between {lo} and {hi}')
    if c['black']>=c['white']:raise ValueError('Black threshold must be below white threshold.')
    for key in ['confidence','track_low_thresh','track_high_thresh','new_track_thresh','match_thresh','iou','appearance_thresh','proximity_thresh']:
        if not isinstance(t[key],(int,float)) or not math.isfinite(t[key]) or not .01<=t[key]<=1:raise ValueError(f'{key} must be between 0.01 and 1.')
    if not t['confidence']<=t['track_low_thresh']<=t['track_high_thresh']<=t['new_track_thresh']:
        raise ValueError('Use detector threshold ≤ recovery threshold ≤ strong-match threshold ≤ new-ID threshold.')
    if not isinstance(t['gap_seconds'],(int,float)) or not math.isfinite(t['gap_seconds']) or not .1<=t['gap_seconds']<=10:raise ValueError('Missing-track memory must be 0.1–10 seconds.')
    if t['imgsz'] not in (640,1024,1536):raise ValueError('Detector resolution must be 640, 1024 or 1536.')
    if type(c['enabled']) is not bool or type(t['with_reid']) is not bool:raise ValueError('Enabled settings must be boolean.')
    return result

def read_settings(path=None):
    return normalize_settings(json.load(open(path)) if path else None)

def color_key(color):
    return json.dumps(color,sort_keys=True)
