#!/usr/bin/env python3
"""
Author: Taihsiang Ho (tai271828)
License: MIT
"""


from watcher import *
import sys

FLAG_DETECTION_USB = False
FLAG_DETECTION_XHCI = False
FLAG_DETECTION_INSERT = False
#FLAG_WHILE_LOOP = True

def callback(filename, lines):
    global FLAG_DETECTION_USB, FLAG_DETECTION_XHCI, FLAG_DETECTION_INSERT
    global FLAG_WHILE_LOOP
    for line in lines:
        line_str = str(line)
        if detect_str(line_str, 'USB'): FLAG_DETECTION_USB = True
        if detect_str(line_str, 'xhci'): FLAG_DETECTION_XHCI = True
        if detect_str(line_str, 'USB Mass Storage device detected'): FLAG_DETECTION_INSERT = True
    if FLAG_DETECTION_USB and FLAG_DETECTION_XHCI and FLAG_DETECTION_INSERT:
        print("An Superspeed USB mass storage was inserted in a xhci controller")
        # stop the watcher loop
        #FLAG_WHILE_LOOP = False
        sys.exit()

def detect_str(line, str_2_detect):
    if str_2_detect in line:
        return True
    return False


watcher = LogWatcher("./", callback, extensions=["plano_watcher"])

#while FLAG_WHILE_LOOP:
watcher.loop()
