# Copyright (c) 2017-present, Facebook, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##############################################################################

"""Detection output visualization module."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import cv2
import numpy as np
import os
import pdb  # 调试

import copy
from lxml.etree import Element, SubElement, tostring, ElementTree
from xml.dom import minidom 
import os.path

import pycocotools.mask as mask_util

from detectron.utils.colormap import colormap
import detectron.utils.env as envu
import detectron.utils.keypoints as keypoint_utils

# Matplotlib requires certain adjustments in some environments
# Must happen before importing matplotlib
envu.set_up_matplotlib()
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

plt.rcParams['pdf.fonttype'] = 42  # For editing in Adobe Illustrator


_GRAY = (218, 227, 218)
_GREEN = (18, 127, 15)
_WHITE = (255, 255, 255)


def kp_connections(keypoints):
    kp_lines = [
        [keypoints.index('left_eye'), keypoints.index('right_eye')],
        [keypoints.index('left_eye'), keypoints.index('nose')],
        [keypoints.index('right_eye'), keypoints.index('nose')],
        [keypoints.index('right_eye'), keypoints.index('right_ear')],
        [keypoints.index('left_eye'), keypoints.index('left_ear')],
        [keypoints.index('right_shoulder'), keypoints.index('right_elbow')],
        [keypoints.index('right_elbow'), keypoints.index('right_wrist')],
        [keypoints.index('left_shoulder'), keypoints.index('left_elbow')],
        [keypoints.index('left_elbow'), keypoints.index('left_wrist')],
        [keypoints.index('right_hip'), keypoints.index('right_knee')],
        [keypoints.index('right_knee'), keypoints.index('right_ankle')],
        [keypoints.index('left_hip'), keypoints.index('left_knee')],
        [keypoints.index('left_knee'), keypoints.index('left_ankle')],
        [keypoints.index('right_shoulder'), keypoints.index('left_shoulder')],
        [keypoints.index('right_hip'), keypoints.index('left_hip')],
    ]
    return kp_lines


def convert_from_cls_format(cls_boxes, cls_segms, cls_keyps):
    """Convert from the class boxes/segms/keyps format generated by the testing
    code.
    """
    box_list = [b for b in cls_boxes if len(b) > 0]
    if len(box_list) > 0:
        boxes = np.concatenate(box_list)
    else:
        boxes = None
    if cls_segms is not None:
        segms = [s for slist in cls_segms for s in slist]
    else:
        segms = None
    if cls_keyps is not None:
        keyps = [k for klist in cls_keyps for k in klist]
    else:
        keyps = None
    classes = []
    for j in range(len(cls_boxes)):
        classes += [j] * len(cls_boxes[j])
    return boxes, segms, keyps, classes


def get_class_string(class_index, score, dataset):
    class_text = dataset.classes[class_index] if dataset is not None else \
        'id{:d}'.format(class_index)
    return class_text + ' {:0.2f}'.format(score).lstrip('0')


def vis_mask(img, mask, col, alpha=0.4, show_border=True, border_thick=1):
    """Visualizes a single binary mask."""

    img = img.astype(np.float32)
    idx = np.nonzero(mask)

    img[idx[0], idx[1], :] *= 1.0 - alpha
    img[idx[0], idx[1], :] += alpha * col

    if show_border:
        contours = cv2.findContours(
            mask.copy(), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)[-2]
        cv2.drawContours(img, contours, -1, _WHITE, border_thick, cv2.LINE_AA)

    return img.astype(np.uint8)


def vis_class(img, pos, class_str, font_scale=0.35):
    """Visualizes the class."""
    img = img.astype(np.uint8)
    x0, y0 = int(pos[0]), int(pos[1])
    # Compute text size.
    txt = class_str
    font = cv2.FONT_HERSHEY_SIMPLEX
    ((txt_w, txt_h), _) = cv2.getTextSize(txt, font, font_scale, 1)
    # Place text background.
    back_tl = x0, y0 - int(1.3 * txt_h)
    back_br = x0 + txt_w, y0
    cv2.rectangle(img, back_tl, back_br, _GREEN, -1)
    # Show text.
    txt_tl = x0, y0 - int(0.3 * txt_h)
    cv2.putText(img, txt, txt_tl, font, font_scale, _GRAY, lineType=cv2.LINE_AA)
    return img


def vis_bbox(img, bbox, thick=1):
    """Visualizes a bounding box."""
    img = img.astype(np.uint8)
    (x0, y0, w, h) = bbox
    x1, y1 = int(x0 + w), int(y0 + h)
    x0, y0 = int(x0), int(y0)
    cv2.rectangle(img, (x0, y0), (x1, y1), _GREEN, thickness=thick)
    return img


def vis_keypoints(img, kps, kp_thresh=2, alpha=0.7):
    """Visualizes keypoints (adapted from vis_one_image).
    kps has shape (4, #keypoints) where 4 rows are (x, y, logit, prob).
    """
    dataset_keypoints, _ = keypoint_utils.get_keypoints()
    kp_lines = kp_connections(dataset_keypoints)

    # Convert from plt 0-1 RGBA colors to 0-255 BGR colors for opencv.
    cmap = plt.get_cmap('rainbow')
    colors = [cmap(i) for i in np.linspace(0, 1, len(kp_lines) + 2)]
    colors = [(c[2] * 255, c[1] * 255, c[0] * 255) for c in colors]

    # Perform the drawing on a copy of the image, to allow for blending.
    kp_mask = np.copy(img)

    # Draw mid shoulder / mid hip first for better visualization.
    mid_shoulder = (
        kps[:2, dataset_keypoints.index('right_shoulder')] +
        kps[:2, dataset_keypoints.index('left_shoulder')]) / 2.0
    sc_mid_shoulder = np.minimum(
        kps[2, dataset_keypoints.index('right_shoulder')],
        kps[2, dataset_keypoints.index('left_shoulder')])
    mid_hip = (
        kps[:2, dataset_keypoints.index('right_hip')] +
        kps[:2, dataset_keypoints.index('left_hip')]) / 2.0
    sc_mid_hip = np.minimum(
        kps[2, dataset_keypoints.index('right_hip')],
        kps[2, dataset_keypoints.index('left_hip')])
    nose_idx = dataset_keypoints.index('nose')
    if sc_mid_shoulder > kp_thresh and kps[2, nose_idx] > kp_thresh:
        cv2.line(
            kp_mask, tuple(mid_shoulder), tuple(kps[:2, nose_idx]),
            color=colors[len(kp_lines)], thickness=2, lineType=cv2.LINE_AA)
    if sc_mid_shoulder > kp_thresh and sc_mid_hip > kp_thresh:
        cv2.line(
            kp_mask, tuple(mid_shoulder), tuple(mid_hip),
            color=colors[len(kp_lines) + 1], thickness=2, lineType=cv2.LINE_AA)

    # Draw the keypoints.
    for l in range(len(kp_lines)):
        i1 = kp_lines[l][0]
        i2 = kp_lines[l][1]
        p1 = kps[0, i1], kps[1, i1]
        p2 = kps[0, i2], kps[1, i2]
        if kps[2, i1] > kp_thresh and kps[2, i2] > kp_thresh:
            cv2.line(
                kp_mask, p1, p2,
                color=colors[l], thickness=2, lineType=cv2.LINE_AA)
        if kps[2, i1] > kp_thresh:
            cv2.circle(
                kp_mask, p1,
                radius=3, color=colors[l], thickness=-1, lineType=cv2.LINE_AA)
        if kps[2, i2] > kp_thresh:
            cv2.circle(
                kp_mask, p2,
                radius=3, color=colors[l], thickness=-1, lineType=cv2.LINE_AA)

    # Blend the keypoints.
    return cv2.addWeighted(img, 1.0 - alpha, kp_mask, alpha, 0)


def vis_one_image_opencv(
        im, boxes, segms=None, keypoints=None, thresh=0.9, kp_thresh=2,
        show_box=False, dataset=None, show_class=False):
    """Constructs a numpy array with the detections visualized."""

    if isinstance(boxes, list):
        boxes, segms, keypoints, classes = convert_from_cls_format(
            boxes, segms, keypoints)

    if boxes is None or boxes.shape[0] == 0 or max(boxes[:, 4]) < thresh:
        return im

    if segms is not None and len(segms) > 0:
        masks = mask_util.decode(segms)
        color_list = colormap()
        mask_color_id = 0

    # Display in largest to smallest order to reduce occlusion
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    sorted_inds = np.argsort(-areas)

    for i in sorted_inds:
        bbox = boxes[i, :4]
        score = boxes[i, -1]
        if score < thresh:
            continue

        # show box (off by default)
        if show_box:
            im = vis_bbox(
                im, (bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]))

        # show class (off by default)
        if show_class:
            class_str = get_class_string(classes[i], score, dataset)
            im = vis_class(im, (bbox[0], bbox[1] - 2), class_str)

        # show mask
        if segms is not None and len(segms) > i:
            color_mask = color_list[mask_color_id % len(color_list), 0:3]
            mask_color_id += 1
            im = vis_mask(im, masks[..., i], color_mask)

        # show keypoints
        if keypoints is not None and len(keypoints) > i:
            im = vis_keypoints(im, keypoints[i], kp_thresh)

    return im
###################################### new add
def id_map_func(rd_id_list):
################ 将算法输出的id值转移为真实的图片标注框id值
    lb_list = []   # 存放真实id标签
    # 定义标注框ID值得映射关系————————已知算法输出VS真实ID值
    id_list = ['id12', 'id13', 'id14', 'id15', 'id18', 'id19', 'id26']  # 目标病灶ID值
    index = { i:k for i,k in enumerate(id_list, 1) }  # 调换i:k的顺序可以改变映射关系
    [i for i,x in enumerate(rd_id_list) if x in index]
    lb_list = list(map(index.get, rd_id_list))

    return lb_list

def txt_file_func(txt_image, txt_label_list, txt_boxes):
    for i in range(txt_boxes.shape[0]):
        temp_text = []
        temp_image_i = txt_image  # 处理的图片名称——根据文件名实时修改
        temp_label_i = txt_label_list[i]
        temp_box_i = txt_boxes[i][:4].tolist()  # 截取前四位——即：标注框的坐标数据
        temp_text.append(temp_image_i)
        temp_text.append(temp_label_i) 
        temp_text = temp_text + temp_box_i  

        if i == 0:
            temp_txt_total = np.array(temp_text)
            temp_txt_total.shape = (1,6)
        else:
            temp_txt_total = np.vstack((temp_txt_total, temp_text))  #np.vstack((a,b)) 垂直组合

    return temp_txt_total

def xml_create_func(xml_path, image_folder, image_name, image_path_ab, image_size, temp_text):
#     xml_path = r'/data/yang/detectron/output/xml_files'  # 创建的xml文件路径
    # 如果不存在xml_path的保存文件夹，则自动创建一个，并且命名为xml_path指定的路径
    if not os.path.exists(xml_path):
        os.mkdir(xml_path)
    
    doc = minidom.Document()
    ########## owner
    annotation_node = doc.createElement('annotation')
    doc.appendChild(annotation_node)
    # folder
    folder_node = doc.createElement('folder')
    annotation_node.appendChild(folder_node)

    folder_txt = doc.createTextNode(image_folder)   # 存放图片的文件夹"to_xlm"
    folder_node.appendChild(folder_txt)
    # filename
    filename_node = doc.createElement('filename')
    annotation_node.appendChild(filename_node)

    filename_txt = doc.createTextNode(image_name)  # 图片名称temp_text[0][0]——修改
    filename_node.appendChild(filename_txt)
    # path
    path_node = doc.createElement('path')
    annotation_node.appendChild(path_node)

    path_txt = doc.createTextNode(image_path_ab)   # 原始图片路径——修改
    path_node.appendChild(path_txt)
    ############ ones#
    # source
    source_node = doc.createElement('source')
    annotation_node.appendChild(source_node)
    database_node = doc.createElement('database')
    source_node.appendChild(database_node)

    database_txt = doc.createTextNode("Unknown")
    database_node.appendChild(database_txt)

    ############# twos#
    # size
    size_node = doc.createElement('size')
    annotation_node.appendChild(size_node)
    # width
    width_node = doc.createElement('width')
    size_node.appendChild(width_node)
    width_txt = doc.createTextNode(str(image_size[1]))  # 原始图片的width
    width_node.appendChild(width_txt)
    # height
    height_node = doc.createElement('height')
    size_node.appendChild(height_node)
    height_txt = doc.createTextNode(str(image_size[0]))  # 原始图片的height
    height_node.appendChild(height_txt)
    # depth
    depth_node = doc.createElement('depth')
    size_node.appendChild(depth_node)
    depth_txt = doc.createTextNode(str(image_size[2]))   # 原始图片的depth
    depth_node.appendChild(depth_txt)
    ############### twoe#
    segmented_node = doc.createElement('segmented')
    annotation_node.appendChild(segmented_node)
    segmented_txt = doc.createTextNode("0")
    segmented_node.appendChild(segmented_txt)
    ############### three# 循环创建多个标注框
    for i in range(temp_text.shape[0]):  # temp_text.shape[0]表征打标框的个数:
        txt_row = temp_text[i]  # 截取每一行全量数据
        txt_file_name = txt_row[0]   ## 图片名称——txt_file_name
        txt_name = txt_row[1]    # 标注框ID值
        txt_xmin = txt_row[2]    # 标注框xmin
        txt_ymin = txt_row[3]    # 标注框ymin
        txt_xmax = txt_row[4]    # 标注框xmax
        txt_ymax = txt_row[5]    # 标注框ymax

        # object
        object_new = doc.createElement('object')
        annotation_node.appendChild(object_new)

        #name
        name_node = doc.createElement('name')
        object_new.appendChild(name_node)
        name_txt = doc.createTextNode(txt_name)  # 对应标注框的ID值——多个打标框的情况，逐个修改ID值
        name_node.appendChild(name_txt)
        # pose
        pose_node = doc.createElement('pose')
        object_new.appendChild(pose_node)
        pose_txt = doc.createTextNode("Unspecified")
        pose_node.appendChild(pose_txt)
        # truncated
        truncated_node = doc.createElement('truncated')
        object_new.appendChild(truncated_node)
        truncated_txt = doc.createTextNode("0")
        truncated_node.appendChild(truncated_txt)
        # difficult
        difficult_node = doc.createElement('difficult')
        object_new.appendChild(difficult_node)
        difficult_txt = doc.createTextNode("0")
        difficult_node.appendChild(difficult_txt)
        ########### threes-1#
        # bndbox
        bndbox = doc.createElement('bndbox')
        object_new.appendChild(bndbox)
        # xmin
        xmin_node = doc.createElement('xmin')
        bndbox.appendChild(xmin_node)
        xmin_txt = doc.createTextNode(txt_xmin)   # 标注框的xmin
        xmin_node.appendChild(xmin_txt)
        # ymin
        ymin_node = doc.createElement('ymin')
        bndbox.appendChild(ymin_node)
        ymin_txt = doc.createTextNode(txt_ymin)  # 标注框的ymin
        ymin_node.appendChild(ymin_txt)
        # xmax
        xmax_node = doc.createElement('xmax')
        bndbox.appendChild(xmax_node)
        xmax_txt = doc.createTextNode(txt_xmax)   # 标注框的xmax
        xmax_node.appendChild(xmax_txt)
        # ymax
        ymax_node = doc.createElement('ymax')
        bndbox.appendChild(ymax_node)
        ymax_txt = doc.createTextNode(txt_ymax)  # 标注框的ymax
        ymax_node.appendChild(ymax_txt)

    ################ 文件保存
    #定义输出的xml文件路径和名称
    temp_xmlfile = xml_path + '/' + txt_file_name[:-4] + '.xml'
    try:
        with open(temp_xmlfile,'w',encoding='UTF-8') as fh:
            # 4.writexml()第一个参数是目标文件对象，第二个参数是根节点的缩进格式，第三个参数是其他子节点的缩进格式，
            # 第四个参数制定了换行格式，第五个参数制定了xml内容的编码。
            doc.writexml(fh, indent='', addindent='\t', newl='\n', encoding='UTF-8')
            print('写入xml OK!')
    except Exception as err:
        print('错误信息：{0}'.format(err))

def vis_one_image(
        im, im_name, output_dir, boxes, segms=None, keypoints=None, thresh=0.9,
        kp_thresh=2, dpi=200, box_alpha=0.0, dataset=None, show_class=False,
        ext='pdf', out_when_no_box=False):
    """Visual debugging of detections."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if isinstance(boxes, list):
        boxes, segms, keypoints, classes = convert_from_cls_format(
            boxes, segms, keypoints)

    if (boxes is None or boxes.shape[0] == 0 or max(boxes[:, 4]) < thresh) and not out_when_no_box:
        return

    dataset_keypoints, _ = keypoint_utils.get_keypoints()

    if segms is not None and len(segms) > 0:
        masks = mask_util.decode(segms)

    color_list = colormap(rgb=True) / 255

    kp_lines = kp_connections(dataset_keypoints)
    cmap = plt.get_cmap('rainbow')
    colors = [cmap(i) for i in np.linspace(0, 1, len(kp_lines) + 2)]

    fig = plt.figure(frameon=False)
    fig.set_size_inches(im.shape[1] / dpi, im.shape[0] / dpi)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    ax.axis('off')
    fig.add_axes(ax)
    ax.imshow(im)

    if boxes is None:
        sorted_inds = [] # avoid crash when 'boxes' is None
    else:
        # Display in largest to smallest order to reduce occlusion
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        sorted_inds = np.argsort(-areas)

    mask_color_id = 0
    ########## add code############
    # 读入路径
    xml_path = r'/data/yang/detectron/output/xml_files'  # 创建的xml文件路径
    # 图片文件夹
    image_path = r'/data/yang/detectron/output/xml_files/'  # 原始图片路径(到图片上一级目录)
    temp_boxes = np.array([[100, 200, 400, 500, 0.8]])  # 定义初始坐标集
    temp_classify_id_list=[]  # 存放ID的list
    for i in sorted_inds:
        bbox = boxes[i, :4]
        score = boxes[i, -1]
        if score < thresh:
            continue
        
        temp_boxes = np.vstack((temp_boxes, boxes[i])) # add有效boxes
#         pdb.set_trace()  # 调试

        # show box (off by default)
        ax.add_patch(
            plt.Rectangle((bbox[0], bbox[1]),
                          bbox[2] - bbox[0],
                          bbox[3] - bbox[1],
                          fill=False, edgecolor='g',
                          linewidth=1.5, alpha=box_alpha))

        if show_class:
            temp_classify_id_list.append(classes[i])  # add有效classes
            ax.text(
                bbox[0], bbox[1] - 2,
                get_class_string(classes[i], score, dataset),
                fontsize=10,
                family='serif',
                bbox=dict(
                    facecolor='g', alpha=0.4, pad=0, edgecolor='none'),
                color='white')

        # show mask
        if segms is not None and len(segms) > i:
            img = np.ones(im.shape)
            color_mask = color_list[mask_color_id % len(color_list), 0:3]
            mask_color_id += 1

            w_ratio = .4
            for c in range(3):
                color_mask[c] = color_mask[c] * (1 - w_ratio) + w_ratio
            for c in range(3):
                img[:, :, c] = color_mask[c]
            e = masks[:, :, i]

            contour = cv2.findContours(
                e.copy(), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)[-2]

            for c in contour:
                polygon = Polygon(
                    c.reshape((-1, 2)),
                    fill=True, facecolor=color_mask,
                    edgecolor='w', linewidth=1.2,
                    alpha=0.5)
                ax.add_patch(polygon)

        # show keypoints
        if keypoints is not None and len(keypoints) > i:
            kps = keypoints[i]
            plt.autoscale(False)
            for l in range(len(kp_lines)):
                i1 = kp_lines[l][0]
                i2 = kp_lines[l][1]
                if kps[2, i1] > kp_thresh and kps[2, i2] > kp_thresh:
                    x = [kps[0, i1], kps[0, i2]]
                    y = [kps[1, i1], kps[1, i2]]
                    line = plt.plot(x, y)
                    plt.setp(line, color=colors[l], linewidth=1.0, alpha=0.7)
                if kps[2, i1] > kp_thresh:
                    plt.plot(
                        kps[0, i1], kps[1, i1], '.', color=colors[l],
                        markersize=3.0, alpha=0.7)

                if kps[2, i2] > kp_thresh:
                    plt.plot(
                        kps[0, i2], kps[1, i2], '.', color=colors[l],
                        markersize=3.0, alpha=0.7)

            # add mid shoulder / mid hip for better visualization
            mid_shoulder = (
                kps[:2, dataset_keypoints.index('right_shoulder')] +
                kps[:2, dataset_keypoints.index('left_shoulder')]) / 2.0
            sc_mid_shoulder = np.minimum(
                kps[2, dataset_keypoints.index('right_shoulder')],
                kps[2, dataset_keypoints.index('left_shoulder')])
            mid_hip = (
                kps[:2, dataset_keypoints.index('right_hip')] +
                kps[:2, dataset_keypoints.index('left_hip')]) / 2.0
            sc_mid_hip = np.minimum(
                kps[2, dataset_keypoints.index('right_hip')],
                kps[2, dataset_keypoints.index('left_hip')])
            if (sc_mid_shoulder > kp_thresh and
                    kps[2, dataset_keypoints.index('nose')] > kp_thresh):
                x = [mid_shoulder[0], kps[0, dataset_keypoints.index('nose')]]
                y = [mid_shoulder[1], kps[1, dataset_keypoints.index('nose')]]
                line = plt.plot(x, y)
                plt.setp(
                    line, color=colors[len(kp_lines)], linewidth=1.0, alpha=0.7)
            if sc_mid_shoulder > kp_thresh and sc_mid_hip > kp_thresh:
                x = [mid_shoulder[0], mid_hip[0]]
                y = [mid_shoulder[1], mid_hip[1]]
                line = plt.plot(x, y)
                plt.setp(
                    line, color=colors[len(kp_lines) + 1], linewidth=1.0,
                    alpha=0.7)

    temp_boxes = np.delete(temp_boxes, 0 ,axis=0)  # 删除无效行
    
    
    #################### 修改参数
    images_folder = "xml_files"   # 存放处理图片的文件夹 
    image_name = im_name.split('/')[-1]  # im_name为图片名全路径
    label_list = id_map_func(temp_classify_id_list) # temp_classify_id_list每次均是随机的——————算法随机输出
    temp_text_total = txt_file_func(image_name, label_list, temp_boxes)
    # 读入原始图片数据 
    image_size_ys = [str(im.shape[k]) for k in range(3)]   # 输出图片的size
    image_path_abs = image_path + images_folder + '/' + image_name   # # 原始图片绝对路径——修改
#     pdb.set_trace()  # 调试
    xml_create_func(xml_path, images_folder, image_name, image_path_abs, image_size_ys, temp_text_total)
#     pdb.set_trace()  # 调试
    
    output_name = os.path.splitext(os.path.basename(im_name))[0]  + os.path.splitext(os.path.basename(im_name))[1] 
    fig.savefig(os.path.join(output_dir, '{}'.format(output_name)), dpi=dpi)
    plt.close('all')
