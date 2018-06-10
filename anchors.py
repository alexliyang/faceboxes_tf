import numpy as np
import itertools
import cv2
import tensorflow as tf

# Anchor configuration
CONFIG = [[1024, 1024, 32, 32, 32, 32, 4], 
          [1024, 1024, 32, 32, 64, 64, 2],
          [1024, 1024, 32, 32, 128, 128, 1],
          [1024, 1024, 64, 64, 256, 256, 1],
          [1024, 1024, 128, 128, 512, 512, 1]] 
VARIANCES = [0.1, 0.2]

def densify(cx, cy, scale_x_norm, scale_y_norm, factor):
    box_width_x = scale_x_norm + (factor - 1)*scale_x_norm/factor 
    box_width_y = scale_y_norm + (factor - 1)*scale_y_norm/factor
    x_top = cx - box_width_x/2
    y_top = cy - box_width_y/2
    slide_x = scale_x_norm/factor
    slide_y = scale_y_norm/factor
    anchor_dense = np.zeros((factor, factor , 4))
    for w, h in itertools.product(range(factor), repeat = 2):
        x = x_top + slide_x*w
        y = y_top + slide_y*h
        anchor_dense[w, h] = np.array([x, y, x + scale_x_norm, y + scale_y_norm])
    return np.reshape(anchor_dense, (factor**2, 4))

def get_boxes(input_config):
    b_out = []
    b_std = []
    shape_stub = []
    for lst in input_config:
        _, b_cur = get_anchor_boxes(lst[0], lst[1], lst[2], lst[3], lst[4], lst[5], lst[6])
        b_std.append(b_cur)
        shape_stub.append(b_cur.shape[:-1])
        b_out.append(np.reshape(b_cur, (-1, 4)).copy())
    return np.vstack(tuple(b_out)), b_std, shape_stub
    
def get_anchor_boxes(shape_dim_x, shape_dim_y, space_x, space_y, scale_x, scale_y, densify_rate, normalised = False):
    # Returns boxes in (left, top, bottom right) form (same as wider) - (0, 0) top left
    # Coordinates stay consistent with OpenCV
    step_x_norm = space_x/shape_dim_x
    step_y_norm = space_y/shape_dim_y
    scale_x_norm = scale_x/shape_dim_x
    scale_y_norm = scale_y/shape_dim_y
    dim_x = int(1/step_x_norm)
    dim_y = int(1/step_y_norm)
    boxes = []
    anchor_centers = np.zeros((dim_y, dim_x, 2))
    anchor_boxes = np.zeros((dim_y, dim_x, densify_rate**2, 4))
    for w, h in itertools.product(range(dim_x), range(dim_y)):
        cx = (w + 0.5)*step_x_norm
        cy = (h + 0.5)*step_y_norm
        cur_center = (cx, cy)
        anchor_centers[h, w] = cur_center
        anchor_boxes[h, w] = densify(cx, cy, scale_x_norm, scale_y_norm, densify_rate)
    if normalised:
        return anchor_centers, anchor_boxes
    else:
        a_c_rest = anchor_centers
        a_c_rest[:, :, 0]*=shape_dim_x
        a_c_rest[:, :, 1]*=shape_dim_y
        bx_rest = anchor_boxes
        bx_rest[:, :, :, 0]*=shape_dim_x
        bx_rest[:, :, :, 1]*=shape_dim_y
        bx_rest[:, :, :, 2]*=shape_dim_x
        bx_rest[:, :, :, 3]*=shape_dim_y
        return np.round(a_c_rest), np.round(anchor_boxes)

def get_shape_stub(shape_dim_x, shape_dim_y, space_x, space_y, densify_rate):
    step_x_norm = space_x/shape_dim_x
    step_y_norm = space_y/shape_dim_y
    dim_x = int(1/step_x_norm)
    dim_y = int(1/step_y_norm)
    return [dim_y, dim_x, densify_rate**2]

def transform_ltbr_to_lbwh(box):
    # Transforms from (left, top, bottom, right) - (0, 0) top left, to (left, bottom, width, height) - (0, 0) top left
    # Used to plot using default rectangle plot in Matplotlib
    # Coordinates stay consistent with OpenCV
    width = np.abs(box[2] - box[0])
    height = np.abs(box[3] - box[1])
    c_p = [box[0], box[1] + height, width, -1*height]
    return c_p

def compute_iou_tf(bboxes1, bboxes2):
    # Extracted from: https://gist.github.com/vierja/38f93bb8c463dce5500c0adf8648d371
    x11, y11, x12, y12 = tf.split(bboxes1, 4, axis=1)
    x21, y21, x22, y22 = tf.split(bboxes2, 4, axis=1)

    xA = tf.maximum(x11, tf.transpose(x21))
    yA = tf.maximum(y11, tf.transpose(y21))
    xB = tf.minimum(x12, tf.transpose(x22))
    yB = tf.minimum(y12, tf.transpose(y22))

    interArea = tf.maximum((xB - xA + 1), 0) * tf.maximum((yB - yA + 1), 0)

    boxAArea = (x12 - x11 + 1) * (y12 - y11 + 1)
    boxBArea = (x22 - x21 + 1) * (y22 - y21 + 1)

    # Fix divide by 0 errors
    iou = interArea / (boxAArea + tf.transpose(boxBArea) - interArea +0.0001)
    return iou

def compute_iou_np(bboxes1, bboxes2):
    # Extracted from: https://medium.com/@venuktan/vectorized-intersection-over-union-iou-in-numpy-and-tensor-flow-4fa16231b63d
    if np.max(bboxes1) < 1.2 and np.min(bboxes1) > -0.2:
        raise Warning('Compute IOU doesn\'t support 0-1 normalised values')
    x11, y11, x12, y12 = np.split(bboxes1, 4, axis=1)
    x21, y21, x22, y22 = np.split(bboxes2, 4, axis=1)

    xA = np.maximum(x11, np.transpose(x21))
    yA = np.maximum(y11, np.transpose(y21))
    xB = np.minimum(x12, np.transpose(x22))
    yB = np.minimum(y12, np.transpose(y22))

    interArea = np.maximum((xB - xA + 1), 0) * np.maximum((yB - yA + 1), 0)

    boxAArea = (x12 - x11 + 1) * (y12 - y11 + 1)
    boxBArea = (x22 - x21 + 1) * (y22 - y21 + 1)

    # Fix divide by 0 errors
    iou = interArea / (boxAArea + np.transpose(boxBArea) - interArea +0.0001)
    return iou

def encode(anchors_all, boxes, threshold = 0.25):
    boxes = np.array(boxes)
    
    iou_mat = anchors.compute_iou_np(anchors_all,np.array(boxes))
    max_iou = np.max(iou_mat, axis = 0) # Compute Maximum IOU values
    max_iou_ids = np.argmax(iou_mat, axis = 0) # Compute Maximum IOU indexes

    # Get corresponding anchor locs
    anchor_boxes = anchors_all[max_iou_ids] 

    centers = (boxes[:, :2] + boxes[:, 2:])/2 - anchor_boxes[:, :2] # Compute centre offset
    wid_height = (boxes[:,2:] - boxes[:,:2]) / (anchor_boxes[:, 2:] - anchor_boxes[:, :2]) # Normalise by height/width of anchor boxes

    # Turns out variances ensure everything is at same scale from SSD implementation https://github.com/rykov8/ssd_keras/issues/53
    centers /= anchors.VARIANCES[0]*anchor_boxes[:, 2:] # (??) https://github.com/lxg2015/faceboxes/blob/master/encoderl.py
    wid_height = np.log(wid_height)/anchors.VARIANCES[1] # Empirically determined from SSD implementation
    cat_items = np.concatenate((centers, wid_height), axis = -1)

    locs = np.zeros((anchors_all.shape[0], 4))
    locs[max_iou_ids] = cat_items
    
    confs = np.zeros((anchors_all.shape[0], 1))
    confs[max_iou_ids] = 1
    confs[max_iou_ids[max_iou < threshold]] = 0 # Zero-out poor matches
    confs = np.eye(2)[np.array(confs, dtype = int)]
    
    return locs, confs