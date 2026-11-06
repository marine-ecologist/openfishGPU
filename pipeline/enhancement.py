"""Fixed video correction. Identical processing is used for stills, detection and output."""
import cv2,numpy as np

def correct_frame(frame,settings):
    if not settings.get('enabled',False):return frame
    x=frame.astype(np.float32)
    x[:,:,0]*=settings['blue_gain']; x[:,:,2]*=settings['red_gain']
    x=np.clip((x-settings['black'])*(255.0/(settings['white']-settings['black'])),0,255)
    x=np.clip(255*np.power(x/255,1/settings['gamma']),0,255).astype(np.uint8)
    if settings['local_contrast']>0:
        lab=cv2.cvtColor(x,cv2.COLOR_BGR2LAB)
        lab[:,:,0]=cv2.createCLAHE(clipLimit=settings['local_contrast'],tileGridSize=(8,8)).apply(lab[:,:,0])
        x=cv2.cvtColor(lab,cv2.COLOR_LAB2BGR)
    if settings['saturation']!=1:
        hsv=cv2.cvtColor(x,cv2.COLOR_BGR2HSV)
        hsv[:,:,1]=np.clip(hsv[:,:,1].astype(np.float32)*settings['saturation'],0,255).astype(np.uint8)
        x=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
    if settings['sharpness']>0:
        x=cv2.addWeighted(x,1+settings['sharpness'],cv2.GaussianBlur(x,(0,0),1.0),-settings['sharpness'],0)
    return x
