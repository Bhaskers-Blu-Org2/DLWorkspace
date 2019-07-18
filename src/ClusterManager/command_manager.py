import json
import os
import time
import argparse
import uuid
import subprocess
import sys
import datetime
import copy

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"../storage"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"../utils"))

from jobs_tensorboard import GenTensorboardMeta
import k8sUtils
import joblog_manager
from osUtils import mkdirsAsUser

import yaml
from jinja2 import Environment, FileSystemLoader, Template
from config import config, GetStoragePath
from DataHandler import DataHandler
from node_manager import get_cluster_status
import base64

import re

import thread
import threading
import random

import logging

logger = logging.getLogger(__name__)

def RunCommand(command):
    dataHandler = DataHandler()
    k8sUtils.kubectl_exec("exec %s %s" % (command["jobId"], command["command"]))
    dataHandler.FinishCommand(command["id"])
    dataHandler.Close()
    return True

def create_log(logdir = '/var/log/dlworkspace'):
    if not os.path.exists(logdir):
        os.system("mkdir -p " + logdir)
    with open('logging.yaml') as f:
        logging_config = yaml.full_load(f)
        f.close()
        logging_config["handlers"]["file"]["filename"] = logdir+"/command_manager.log"
        logging.config.dictConfig(logging_config)

def Run():
    create_log()
    while True:
        try:
            dataHandler = DataHandler()
            pendingCommands = dataHandler.GetPendingCommands()
            for command in pendingCommands:
                try:
                    logger.info("Processing command: %s", command["id"])
                    RunCommand(command)
                except Exception as e:
                    logger.exception("run command failed")
        except Exception as e:
            logger.exception("getting command failed")
        time.sleep(1)

if __name__ == '__main__':
    Run()
