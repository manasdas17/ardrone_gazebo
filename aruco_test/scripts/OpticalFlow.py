#!/usr/bin/env python
from __future__ import print_function

import roslib
roslib.load_manifest('opticalflow_controller')
import sys
import rospy
import numpy as np
import cv2
from common import draw_str
from sensor_msgs.msg import Image
from geometry_msgs.msg import Twist
from cv_bridge import CvBridge, CvBridgeError
import time

lk_params = dict(winSize  = (15, 15),
                 maxLevel = 2,
                 criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))

feature_params = dict(maxCorners = 500,
                      qualityLevel = 0.05,
                      minDistance = 7,
                      blockSize = 7)

front_time = 2000
turn_time = 2000

class optical_flow:

  def __init__(self):
    self.past_time = int(round(time.time() * 1000))
    self.turn_flag = False
    self.counter = -1

    self.track_len = 10
    self.detect_interval = 5
    self.tracks = []
    self.frame_idx = 0
    self.bridge = CvBridge()
    self.image_sub = rospy.Subscriber("/vizzy/r_camera/image_rect_color",
                                      Image, self.callback)
    print("Subscriber initialized")

    self.ctrl_pub = rospy.Publisher('/vizzy/cmd_vel', Twist, queue_size = 1)
    print("Publisher initialized")

  def reactive_controller(self, size_l, size_r):
    twist = Twist()
    l_r_sum = size_l + size_r
    l_r_sum_abs = abs(size_l) + abs(size_r)

    if l_r_sum_abs >= 15:
        twist.linear.x = 0
        twist.angular.z = 0.0
        print('Stop: ', l_r_sum, l_r_sum_abs, size_l, size_r)
    elif abs(l_r_sum) <= 6: #(l_r_sum_abs * 50 / 100):
        twist.linear.x = 0.50
        twist.angular.z = 0.0
        print('Forward: ', l_r_sum, l_r_sum_abs, size_l, size_r)
    else:
        twist.linear.x = 0.50
        twist.angular.z = l_r_sum / l_r_sum_abs
        print('Turn: ', l_r_sum, l_r_sum_abs, size_l, size_r)

    return twist

  def reactive_controller2(self, size_l, size_r):
    twist = Twist()
    l_r_sum = size_l + size_r
    l_r_sum_abs = abs(size_l) + abs(size_r)

    if ((abs(l_r_sum) <= (l_r_sum_abs * 20 / 100)) or (self.counter <= front_time)) and (self.turn_flag == False):
#    if ((abs(l_r_sum) <= 0.5) or (self.counter <= front_time)) and (self.turn_flag == False):
      if self.counter == -1:
        self.past_time = int(round(time.time() * 1000))
      time_now = int(round(time.time() * 1000))
      self.counter = time_now - self.past_time
      twist.linear.x = 0.50
      twist.angular.z = 0.0
      print('Forward: ', self.counter, time_now, self.past_time)
    else:
      if self.turn_flag == False:
        self.past_time = int(round(time.time() * 1000))
        self.turn_flag = True
      self.counter = int(round(time.time() * 1000)) - self.past_time
      if self.counter > turn_time:
        self.turn_flag = False
        self.counter = -1
      twist.linear.x = 0.25
      twist.angular.z = np.sign(l_r_sum) * 0.50
      print('Turn: ', self.counter)
      #twist.linear.x = 0.50
      #twist.angular.z = l_r_sum / 20

    return twist

  def calc_mean(self, img, p0, p1, good):
    h, w = img.shape[:2]
    #vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    vis = img.copy()
    #variables for the mean
    mean_l_x = 0
    mean_l_y = 0
    mean_l_vx = 0
    mean_l_vy = 0
    total_l = 0
    size_l = 0
    mean_r_x = 0
    mean_r_y = 0
    mean_r_vx = 0
    mean_r_vy = 0
    total_r = 0
    size_r = 0
    for (x1, y1), (x2, y2), good_flag in zip(np.int32(p0.reshape(-1, 2)),
                                             np.int32(p1.reshape(-1, 2)), good):
      #checks for the mean
      if good_flag:
        if x1 < w / 2:
          total_l += 1
          mean_l_x += x1
          mean_l_y += y1
          mean_l_vx += x2 - x1
          mean_l_vy += y2 - y1
          size_l = np.sqrt(pow(mean_l_vx, 2) + pow(mean_l_vy, 2))
        else:
          total_r += 1
          mean_r_x += x1
          mean_r_y += y1
          mean_r_vx += x2 - x1
          mean_r_vy += y2 - y1
          size_r = np.sqrt(pow(mean_r_vx, 2) + pow(mean_r_vy, 2))
    #calculating the mean
    if total_l > 0:
      mean_l_x /= total_l
      mean_l_y /= total_l
      mean_l_vx /= total_l
      mean_l_vy /= total_l
      size_l = size_l / total_l * np.sign(mean_l_vx)
    if total_r > 0:
      mean_r_x /= total_r
      mean_r_y /= total_r
      mean_r_vx /= total_r
      mean_r_vy /= total_r
      size_r = size_r / total_r * np.sign(mean_r_vx)
    cv2.line(vis, (np.int32(w / 4), np.int32(h / 2)),
            (np.int32(w / 4 + size_l), np.int32(h / 2)),
            (0, 0, 255), 1, 8, 0)
    cv2.circle(vis, (np.int32(w / 4 + size_l), np.int32(h / 2)),
               2, (0, 0, 255), -1)
    cv2.line(vis, (np.int32(w * 3 / 4), np.int32(h / 2)),
            (np.int32(w * 3 / 4 + size_r), np.int32(h / 2)),
            (0, 0, 255), 1, 8, 0)
    cv2.circle(vis, (np.int32(w * 3 / 4 + size_r), np.int32(h / 2)),
               2, (0, 0, 255), -1)
    return vis, size_l, size_r

  def callback(self,data):
    try:
      cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
    except CvBridgeError as e:
      print(e)

    frame_gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    vis = cv_image.copy()

    if len(self.tracks) > 0:
        img0, img1 = self.prev_gray, frame_gray
        p0 = np.float32([tr[-1] for tr in self.tracks]).reshape(-1, 1, 2)
        p1, st, err = cv2.calcOpticalFlowPyrLK(img0, img1, p0, None, **lk_params)
        p0r, st, err = cv2.calcOpticalFlowPyrLK(img1, img0, p1, None, **lk_params)
        d = abs(p0-p0r).reshape(-1, 2).max(-1)
        good = d < 1
        new_tracks = []
        for tr, (x, y), good_flag in zip(self.tracks, p1.reshape(-1, 2), good):
            if not good_flag:
                continue
            tr.append((x, y))
            if len(tr) > self.track_len:
                del tr[0]
            new_tracks.append(tr)
            cv2.circle(vis, (x, y), 2, (0, 255, 0), -1)
        self.tracks = new_tracks
        cv2.polylines(vis, [np.int32(tr) for tr in self.tracks], False, (0, 255, 0))
        draw_str(vis, (20, 20), 'track count: %d' % len(self.tracks))
        vis, size_l, size_r = self.calc_mean(vis, p0, p1, good)
        draw_str(vis, (20, 40), 'Lenght left: %f' % size_l)
        draw_str(vis, (20, 60), 'Lenght right: %f' % size_r)
        self.ctrl_pub.publish(self.reactive_controller(size_l, size_r))

    if self.frame_idx % self.detect_interval == 0:
        mask = np.zeros_like(frame_gray)
        mask[:] = 255
        for x, y in [np.int32(tr[-1]) for tr in self.tracks]:
            cv2.circle(mask, (x, y), 5, 0, -1)
        p = cv2.goodFeaturesToTrack(frame_gray, mask = mask, **feature_params)
        if p is not None:
            for x, y in np.float32(p).reshape(-1, 2):
                self.tracks.append([(x, y)])


    self.frame_idx += 1
    self.prev_gray = frame_gray

    cv2.imshow("Image window", vis)

def main(args):
  cv2.startWindowThread()
  cv2.namedWindow("Image window")
  of = optical_flow()
  rospy.init_node('optical_flow', anonymous=True)
  try:
    rospy.spin()
  except KeyboardInterrupt:
    print("Shutting down")
  cv2.destroyAllWindows()

if __name__ == '__main__':
    main(sys.argv)