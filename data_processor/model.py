import os
import requests

import torch
import torchvision.models as models

from utils.config import InitedByConfig

model_urls = {
    'resnet18': 'https://download.pytorch.org/models/resnet18-5c106cde.pth',
    'resnet34': 'https://download.pytorch.org/models/resnet34-333f7ec4.pth',
    'resnet50': 'https://download.pytorch.org/models/resnet50-19c8e357.pth',
    'resnet101': 'https://download.pytorch.org/models/resnet101-5d3b4d8f.pth',
    'resnet152': 'https://download.pytorch.org/models/resnet152-b121ed2d.pth',
    'vgg19': 'https://download.pytorch.org/models/vgg19-dcbb9e9d.pth',
    'densenet201': 'https://download.pytorch.org/models/densenet201-c1103571.pth'
}

start_modes = ['begin', 'url', 'continue']


class Model(InitedByConfig):
    class ModelException(Exception):
        def __init__(self, message):
            super(Model.ModelException, self).__init__(message)
            self.__message = message

        def __str__(self):
            return self.__message

    def __init__(self, config: {}):
        super().__init__()
        self.__model = None
        self.__config = config
        self.__model = getattr(models, self.__config['architecture'])()

        self.__init_from_config()

    def model(self):
        return self.__model

    def __init_from_config(self):
        start_mode = self.__config_start_mode()
        if start_mode == start_modes[0]:
            return

        self.__weights_dir = os.path.join(self.__config['workdir_path'], 'weights')
        self.__weights_file = os.path.join(self.__weights_dir, "weights.pth")

    def __load_weights_by_url(self):
        model_url = model_urls[self.__config['architecture']]
        init_weights_file = os.path.join(self.__weights_dir, model_url.split("/")[-1])

        if not os.path.isfile(init_weights_file):
            if not os.path.exists(self.__weights_dir) or not os.path.isdir(self.__weights_dir):
                os.makedirs(self.__weights_dir)
            response = requests.get(model_url)
            with open(init_weights_file, 'wb') as file:
                file.write(response.content)

    def load_weights(self, weights_file: str, url=False):
        pretrained_weights = torch.load(weights_file)
        # # pretrained_weights = {k: v for k, v in pretrained_weights.items() if k in self.__model.state_dict()}
        # from collections import OrderedDict
        # new_state_dict = OrderedDict()
        # for k, v in pretrained_weights.items():
        #     name = k[7:]  # remove `module.`
        #     new_state_dict[name] = v

        if not url:
            self.__model.classifier = torch.nn.Linear(self.__model.classifier.in_features, 128)
            self.__model = torch.nn.DataParallel(self.__model)
            pretrained_weights = {k: v for k, v in pretrained_weights.items() if k in self.__model.state_dict()}
            self.__model.load_state_dict(pretrained_weights)
        else:
            self.__load_weights_by_url()
            self.__model.load_state_dict(pretrained_weights)
            self.__model.classifier = torch.nn.Linear(self.__model.classifier.in_features, 128)
            self.__model = torch.nn.DataParallel(self.__model)

    def save_weights(self, weights_path):
        torch.save(self.__model.state_dict(), weights_path)

    def __config_start_mode(self):
        return self.__config['network']['start_from']

    def _required_params(self):
        return {"data_processor": {
            "architecture": ["resnet34"],
            "weights_dir": ["weights"],
            "start_from": ["begin", "url"]
        },
            "workdir_path": "workdir"
        }

    def __call__(self, x):
        return self.__model(x)
