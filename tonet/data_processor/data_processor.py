import torch
from tqdm import tqdm

from tonet.tonet.utils.file_structure_manager import FileStructManager
from .model import Model
from .monitoring import Monitor
from tonet.tonet.utils.config import InitedByConfig


class DataProcessor(InitedByConfig):
    class LearningRate:
        def __init__(self, config: {}):
            self.__value = float(config['learning_rate']['start_value'])
            self.__decrease_coefficient = float(config['learning_rate']['decrease_coefficient'])

            if 'first_epoch_decrease_coeff' in config['learning_rate']:
                self.__first_epoch_decrease_coeff = float(
                    config['learning_rate']['first_epoch_decrease_coeff'])
            else:
                self.__first_epoch_decrease_coeff = None

            self.__skip_steps_number = config['learning_rate']['skip_steps_number']
            self.__cur_step = 0

        def value(self, cur_loss, min_loss) -> float:
            if min_loss is not None and cur_loss < min_loss:
                print("Clear steps num")
                self.__cur_step = 0

            if self.__cur_step == 1 and self.__first_epoch_decrease_coeff is not None:
                self.__value /= self.__first_epoch_decrease_coeff
                self.__first_epoch_decrease_coeff = None
                print('Decrease lr cause 1 step to', self.__value)
            elif self.__cur_step > 0 and (self.__cur_step % self.__skip_steps_number) == 0:
                self.__value /= self.__decrease_coefficient
                print('Decrease lr to', self.__value)

            self.__cur_step += 1

            return self.__value

    def __init__(self, config: {}, file_struct_manadger: FileStructManager):
        self.__is_cuda = True
        self.__file_struct_manager = file_struct_manadger

        self.__model = Model(config, self.__file_struct_manager)
        self.__learning_rate = self.LearningRate(config)

        self.__optimizer_fnc = getattr(torch.optim, config['optimizer'])
        self.__optimizer = self.__optimizer_fnc(params=self.__model.model().parameters(), weight_decay=1.e-4,
                                                lr=self.__learning_rate.value(0, 0))

        self.__criterion = torch.nn.CrossEntropyLoss()
        if self.__is_cuda:
            self.__criterion = self.__criterion.cuda()

        self.__monitor = Monitor(config, self.__file_struct_manager)
        self.clear_metrics()

        self.__epoch_num = 0

    def predict(self, data, is_train=False):
        if self.__is_cuda:
            data = data.cuda(async=is_train)

        if is_train:
            self.__model.model().train()
        else:
            self.__model.model().eval()

        input_var = torch.autograd.Variable(data, volatile=not is_train)
        output = self.__model.model()(input_var)
        return torch.max(output.data, 1), output

    def process_batch(self, input, target, is_train):
        self.__model.model().train(is_train)

        if self.__is_cuda:
            target = target.cuda(async=True)

        inputs_num = input.size(0)
        target_var = torch.autograd.Variable(target, volatile=not is_train)

        if is_train:
            self.__optimizer.zero_grad()

        [_, preds], output = self.predict(input, is_train)

        if is_train:
            loss = self.__criterion(output, target_var)
            loss.backward()
            self.__metrics['loss'] += loss.data[0] * inputs_num
            self.__metrics['train_accuracy'] += torch.sum(preds == target_var.data)

            # torch.nn.utils.clip_grad_norm(self.__model.parameters(), 1 / 128.)
            self.__optimizer.step()
        else:
            loss = self.__criterion(output, target_var)
            self.__metrics['val_loss'] += loss.data[0] * inputs_num
            self.__metrics['val_accuracy'] += torch.sum(preds == target_var.data)

        self.__images_processeed['train' if is_train else 'val'] += inputs_num

    def train_epoch(self, train_dataloader, validation_dataloader, epoch_idx: int):
        for batch in tqdm(train_dataloader, desc="train", leave=False):
            self.process_batch(batch['data'], batch['target'], is_train=True)
        for batch in tqdm(validation_dataloader, desc="validation", leave=False):
            self.process_batch(batch['data'], batch['target'], is_train=False)

        cur_metrics = self.get_metrics()

        self.__optimizer = self.__optimizer_fnc(params=self.__model.model().parameters(), weight_decay=1.e-4,
                                                lr=self.__learning_rate.value(cur_metrics['val_loss'],
                                                                              self.__monitor.get_metrics_min_val('val_loss')))

        self.__monitor.update(epoch_idx, cur_metrics)
        self.clear_metrics()

    def get_metrics(self):
        val_acc = self.__metrics['val_accuracy'] / self.__images_processeed['val']
        train_acc = self.__metrics['train_accuracy'] / self.__images_processeed['train']
        return {"loss": self.__metrics['loss'] / self.__images_processeed['train'],
                "val_loss": self.__metrics['val_loss'] / self.__images_processeed['train'],
                "val_accuracy": val_acc,
                "train_accuracy": train_acc,
                "train_min_val_acc": train_acc - val_acc}

    def clear_metrics(self):
        self.__metrics = {"loss": 0, "val_loss": 0, "val_accuracy": 0, "train_accuracy": 0, "train_min_val_acc": 0}
        self.__images_processeed = {"val": 0, "train": 0}

    def get_state(self):
        return {'weights': self.__model.model().state_dict(), 'optimizer': self.__optimizer.state_dict()}

    def load_state(self, optimizer_state: str):
        state = torch.load(optimizer_state)
        state = {k: v for k, v in state.items() if k in self.__optimizer.state_dict()}
        self.__optimizer.load_state_dict(state)

    def load_weights(self, path):
        self.__model.load_weights(path)

    def save_weights(self):
        self.__model.save_weights()

    def save_state(self):
        torch.save(self.__optimizer.state_dict(), self.__file_struct_manager.optimizer_state_file())

    def close(self):
        self.__monitor.close()

    def _required_params(self):
        return {
            "network": {
                "optimiser": ["Adam", "SGD"],
                "learning_rate": "Learning rate value",
            },
            "workdir_path": "workdir"
        }