import torch
import numpy as np
from torch.utils.data import Dataset
from torchvision import datasets, transforms
from math import floor
from collections import defaultdict
import random
import cv2

from attack_models.autoencoders import *
from attack_models.unet import *

import math

import os

import copy
IMAGENET_DEFAULT_MEAN = (0.485, 0.456, 0.406)
IMAGENET_DEFAULT_STD = (0.229, 0.224, 0.225)
class H5Dataset(Dataset):
    def __init__(self, dataset, client_id):
        self.targets = torch.LongTensor(dataset[client_id]['label'])
        self.inputs = torch.Tensor(dataset[client_id]['pixels'])
        shape = self.inputs.shape
        self.inputs = self.inputs.view(shape[0], 1, shape[1], shape[2])
        
    def classes(self):
        return torch.unique(self.targets)
    
    def __add__(self, other): 
        self.targets = torch.cat( (self.targets, other.targets), 0)
        self.inputs = torch.cat( (self.inputs, other.inputs), 0)
        return self
    
    def to(self, device):
        self.targets = self.targets.to(device)
        self.inputs = self.inputs.to(device)
        
        
    def __len__(self):
        return self.targets.shape[0]

    def __getitem__(self, item):
        inp, target = self.inputs[item], self.targets[item]
        return inp, target
    

class DatasetSplit(Dataset):
    """ An abstract Dataset class wrapped around Pytorch Dataset class """
    def __init__(self, dataset, idxs):
        self.dataset = dataset
        self.idxs = idxs

        if self.idxs != None:
            random.shuffle(idxs)
            self.targets = torch.Tensor([self.dataset.targets[idx] for idx in idxs])

    def classes(self):
            return torch.unique(self.targets)  

    def __len__(self):
        if self.idxs == None:
            return len(self.dataset)
        else:
            return len(self.idxs)
        

    def __getitem__(self, item):
        if self.idxs != None:
            inp, target = self.dataset[self.idxs[item]]
        else:
            inp, target = self.dataset[item]
        return inp, target

def enumerate_batch(dataset_ld, mode, batch_size=32, args = None, agent_id = -1, val_mode = False):
    num_sample=len(dataset_ld)
    num_batches = int(math.ceil(num_sample / batch_size))

    for i_batch in range(num_batches):
        # split one batch to clean and pos two parts
        batch_X_clean, batch_Y_clean  = [], []
        batch_X_pos_ifc, batch_Y_pos_ifc  = [], []
        start = i_batch * batch_size
        end = min((i_batch + 1) * batch_size, num_sample)
        for i_img in range(start,end):
            #pos_state= i_img in dataset_ld.malicious_idx_list

            if mode == 'benign':
                img,label=dataset_ld[i_img]
                batch_X_clean.append(img.unsqueeze(0))
                batch_Y_clean.append([label])

            elif mode == 'malicious':
                img,label=dataset_ld[i_img]
                batch_X_clean.append(copy.deepcopy(img.unsqueeze(0)))
                batch_Y_clean.append([label])

                if args.attack_mode == 'DBA' or args.attack_mode == 'normal':
                    img = add_pattern_bd(img, args.data, args.pattern_type, agent_id, args.attack_mode, val_mode)
                batch_X_pos_ifc.append(img.unsqueeze(0))

                transformed_label = single_label_transform(label, args)
                batch_Y_pos_ifc.append([transformed_label])


        if mode == 'malicious':
            yield torch.cat(batch_X_clean,0),torch.Tensor(batch_Y_clean).long(),\
                torch.cat(batch_X_pos_ifc,0),torch.Tensor(batch_Y_pos_ifc).long()
        elif mode == 'benign':
            yield torch.cat(batch_X_clean,0),torch.Tensor(batch_Y_clean).long(), None, None

def distribute_data_dirchlet(dataset, args, n_classes = 10):
        if args.num_agents == 1:
            return {0:range(len(dataset))}
        N = dataset.targets.shape[0]
        net_dataidx_map = {}

        idx_batch = [[] for _ in range(args.num_agents)]
        for k in range(n_classes):
            idx_k = np.where(dataset.targets == k)[0]
            np.random.shuffle(idx_k)

            proportions = np.random.dirichlet(np.repeat(args.beta, args.num_agents))
            proportions = proportions / proportions.sum()
            proportions = (np.cumsum(proportions) * len(idx_k)).astype(int)[:-1]

            idx_batch = [idx_j + idx.tolist() for idx_j, idx in zip(idx_batch, np.split(idx_k, proportions))]


        for j in range(args.num_agents):
            np.random.shuffle(idx_batch[j])
            net_dataidx_map[j] = idx_batch[j]

        return net_dataidx_map

def distribute_data_average(dataset, args, n_classes=10, class_per_agent=10):
    if args.num_agents == 1:
        return {0:range(len(dataset))}
    
    def chunker_list(seq, size):
        return [seq[i::size] for i in range(size)]
    
    # sort labels
    labels_sorted = dataset.targets.sort()
    # create a list of pairs (index, label), i.e., at index we have an instance of  label
    class_by_labels = list(zip(labels_sorted.values.tolist(), labels_sorted.indices.tolist()))
    # convert list to a dictionary, e.g., at labels_dict[0], we have indexes for class 0
    labels_dict = defaultdict(list)
    for k, v in class_by_labels:
        labels_dict[k].append(v)
        
    # split indexes to shards
    shard_size = len(dataset) // (args.num_agents * class_per_agent)
    slice_size = (len(dataset) // n_classes) // shard_size    
    for k, v in labels_dict.items():
        labels_dict[k] = chunker_list(v, slice_size)
           
    # distribute shards to users
    dict_users = defaultdict(list)
    for user_idx in range(args.num_agents):
        class_ctr = 0
        for j in range(0, n_classes):
            if class_ctr == class_per_agent:
                    break
            elif len(labels_dict[j]) > 0:
                dict_users[user_idx] += labels_dict[j][0]
                del labels_dict[j%n_classes][0]
                class_ctr+=1

    return dict_users       

def get_trasform(args):
    transforms_list = []

    transforms_list.append(transforms.Resize((args.input_height, args.input_width)))
    transforms_list.append(transforms.ToTensor())
    if args.data == 'mnist':
        transforms_list.append(transforms.Normalize([0.5], [0.5]))
    elif args.data == 'fmnist':
        transforms_list.append(transforms.Normalize(mean=[0.2860], std=[0.3530]))
    elif args.data == 'cifar10':
        transforms_list.append(transforms.Normalize(mean=(0.4914, 0.4822, 0.4465), std=(0.2023, 0.1994, 0.2010)))
    elif args.data == 'tiny-imagenet':
        transforms_list.append(transforms.Normalize(IMAGENET_DEFAULT_MEAN, IMAGENET_DEFAULT_STD))
    
    return transforms.Compose(transforms_list)


def get_datasets(args):
    """ returns train and test datasets """
    get_image_parameter(args)
    transform = get_trasform(args)

    train_dataset, test_dataset = None, None
    data_dir = '../data'
    if args.data == 'mnist':
        train_dataset = datasets.MNIST(data_dir, train=True, download=True, transform=transform)
        test_dataset = datasets.MNIST(data_dir, train=False, download=True, transform=transform)
        
    if args.data == 'fmnist':
        train_dataset = datasets.FashionMNIST(data_dir, train=True, download=True, transform=transform)
        test_dataset = datasets.FashionMNIST(data_dir, train=False, download=True, transform=transform)
    
    elif args.data == 'fedemnist':
        train_dir = '../data/Fed_EMNIST/fed_emnist_all_trainset.pt'
        test_dir = '../data/Fed_EMNIST/fed_emnist_all_valset.pt'
        train_dataset = torch.load(train_dir)
        test_dataset = torch.load(test_dir) 
    
    elif args.data == 'cifar10':
        train_dataset = datasets.CIFAR10(data_dir, train=True, download=True, transform=transform)
        test_dataset = datasets.CIFAR10(data_dir, train=False, download=True, transform=transform)
        train_dataset.targets, test_dataset.targets = torch.LongTensor(train_dataset.targets), torch.LongTensor(test_dataset.targets)  
    elif args.data == 'tiny-imagenet':
        train_dataset = datasets.ImageFolder(
            os.path.join(data_dir, 'tiny-imagenet-200', 'train'), transform=transform)

        test_dataset = datasets.ImageFolder(
            os.path.join(data_dir, 'tiny-imagenet-200', 'test'), transform=transform)
    return train_dataset, test_dataset

def get_image_parameter(args):
    if args.data == "cifar10":
        args.input_height = 32
        args.input_width = 32
        args.input_channel = 3
        args.num_classes = 10

    elif args.data == "mnist":
        args.input_height = 28
        args.input_width = 28
        args.input_channel = 1
        args.num_classes = 10

    elif args.data in "tiny-imagenet":
        args.input_height = 64
        args.input_width = 64
        args.input_channel = 3
        args.num_classes = 200


def get_noise_generator(args):
    noise_model = None
    if args.data == 'cifar10':
        noise_model = UNet(3).to(args.device)

    elif args.data == 'mnist':
        noise_model = MNISTAutoencoder().to(args.device)

    elif args.data =='tiny-imagenet':
        if args.attack_model == None:
            noise_model = MNISTAutoencoder().to(args.device)

        elif args.attack_model == 'unet':
            noise_model = UNet(3).to(args.device)
    
    return noise_model

def get_loss_n_accuracy_normal(model, criterion, data_loader, args, num_classes=10):
    """ Returns the loss and total accuracy, per class accuracy on the supplied data loader """
    
    # disable BN stats during inference
    model.eval()                                      
    total_loss, correctly_labeled_samples = 0, 0
    confusion_matrix = torch.zeros(num_classes, num_classes)
            
    # forward-pass to get loss and predictions of the current batch
    for _, (inputs, labels) in enumerate(data_loader):
        inputs, labels = inputs.to(device=args.device, non_blocking=True),\
                labels.to(device=args.device, non_blocking=True)
                                            
        # compute the total loss over minibatch
        outputs = model(inputs)
        avg_minibatch_loss = criterion(outputs, labels)
        total_loss += avg_minibatch_loss.item()*outputs.shape[0]
                        
        # get num of correctly predicted inputs in the current batch
        _, pred_labels = torch.max(outputs, 1)
        pred_labels = pred_labels.view(-1)
        correctly_labeled_samples += torch.sum(torch.eq(pred_labels, labels)).item()
        # fill confusion_matrix
        for t, p in zip(labels.view(-1), pred_labels.view(-1)):
            confusion_matrix[t.long(), p.long()] += 1
                                
    avg_loss = total_loss / len(data_loader.dataset)
    accuracy = correctly_labeled_samples / len(data_loader.dataset)
    per_class_accuracy = confusion_matrix.diag() / confusion_matrix.sum(1)
    return avg_loss, (accuracy, per_class_accuracy)

def get_loss_n_accuracy_poison(model, trigger_generator, criterion, val_dataset, args, num_classes=10):
    """ Returns the loss and total accuracy, per class accuracy on the supplied data loader """
    
    # disable BN stats during inference
    model.eval()                                      
    total_loss, correctly_labeled_samples = 0, 0
    confusion_matrix = torch.zeros(num_classes, num_classes)
            
    # forward-pass to get loss and predictions of the current batch
    if args.attack_mode == 'DBA' or args.attack_mode == 'normal':
        for _, _, poison_inputs, poison_labels in enumerate_batch(val_dataset, 'malicious', args.bs, args, val_mode = True):

            inputs, labels = poison_inputs.to(device=args.device, non_blocking=True),\
                    poison_labels.to(device=args.device, non_blocking=True)


            # compute the total loss over minibatch
            outputs = model(inputs)
            avg_minibatch_loss = criterion(outputs, labels.view(-1,))
            total_loss += avg_minibatch_loss.item()*outputs.shape[0]
                            
            # get num of correctly predicted inputs in the current batch
            _, pred_labels = torch.max(outputs, 1)
            pred_labels = pred_labels.view(-1)
            correctly_labeled_samples += torch.sum(torch.eq(pred_labels, labels.view(-1,))).item()
            # fill confusion_matrix
            for t, p in zip(labels.view(-1), pred_labels.view(-1)):
                confusion_matrix[t.long(), p.long()] += 1

    elif args.attack_mode == 'trigger_generation':
        for inputs, labels,_,_  in enumerate_batch(val_dataset, 'malicious', args.bs, args, val_mode = True):

            inputs, labels = poison_inputs.to(device=args.device, non_blocking=True),\
                    poison_labels.to(device=args.device, non_blocking=True)

            inputs = trigger_generator(inputs) * args.noise_eps + inputs
            labels = target_transform(labels, args)

            # compute the total loss over minibatch
            outputs = model(inputs)
            avg_minibatch_loss = criterion(outputs, labels.view(-1, ))
            total_loss += avg_minibatch_loss.item()*outputs.shape[0]
                            
            # get num of correctly predicted inputs in the current batch
            _, pred_labels = torch.max(outputs, 1)
            pred_labels = pred_labels.view(-1)
            correctly_labeled_samples += torch.sum(torch.eq(pred_labels, labels.view(-1,))).item()
            # fill confusion_matrix
            for t, p in zip(labels.view(-1), pred_labels.view(-1)):
                confusion_matrix[t.long(), p.long()] += 1
                
    avg_loss = total_loss / len(val_dataset)
    accuracy = correctly_labeled_samples / len(val_dataset)
    per_class_accuracy = confusion_matrix.diag() / confusion_matrix.sum(1)

    return avg_loss, (accuracy, per_class_accuracy)

def target_transform(x, args):

    if args.mode == 'all2one':
        attack_target = args.target_class
        return torch.ones_like(x) * attack_target
    elif args.mode == 'all2all':
        num_classes = args.num_classes
        return (x + 1) % num_classes

def single_label_transform(label, args):
    if args.poison_mode == 'all2one':
        return args.target_class
    elif args.poison_mode == 'all2all':
        return (label + 1) % args.num_classes

def split_malicious_dataset(dataset, args, data_idxs=None, poison_all=False):
    all_idxs = (dataset.targets == args.base_class).nonzero().flatten().tolist()
    if data_idxs != None:
        all_idxs = list(set(all_idxs).intersection(data_idxs))
        
    poison_frac = 1 if poison_all else args.poison_frac    
    poison_idxs = random.sample(all_idxs, floor(poison_frac*len(all_idxs)))
    
    dataset.self.malicious_idx_list = list(poison_idxs)
    dataset.malicious_label = args.target_class

    #benign_idxs = list(set(all_idxs) - set(poison_idxs))

    #benign_dataset = DatasetSplit(dataset, benign_idxs)
    #malicious_dataset = DatasetSplit(dataset, poison_idxs)
    #return benign_dataset, malicious_dataset


def add_pattern_bd(x, dataset='cifar10', pattern_type='square', agent_idx=-1, mode = 'normal', val_mode = False):
    """
    adds a trojan pattern to the image
    """
    original_shape = x.shape
    x = x.squeeze()
    
    if mode == 'normal' or val_mode == True:
        if dataset == 'cifar10' or dataset == 'tiny-imagenet':
            if pattern_type == 'vertical_line':
                start_idx = 5
                size = 6
                # vertical line
                for d in range(0, 3):  
                    for i in range(start_idx, start_idx+size+1):
                        x[i, start_idx][d] = 0
                # horizontal line
                for d in range(0, 3):  
                    for i in range(start_idx-size//2, start_idx+size//2 + 1):
                        x[start_idx+size//2, i][d] = 0
            elif pattern_type == 'pixel':
                pattern_type = [[[0, 0], [0, 1], [0, 2], [0, 3]],
                [[0, 6], [0, 7], [0, 8], [0, 9]],
                [[3, 0], [3, 1], [3, 2], [3, 3]],
                [[3, 6], [3, 7], [3, 8], [3, 9]]]
                for d in range(0, 3):
                    for i in range(len(pattern_type)):
                        for j in range(len(pattern_type[i])):
                            pos = pattern_type[i][j]
                            x[pos[0]][pos[1]][d] = 1
        elif dataset == 'mnist':
            if pattern_type == 'square':
                for i in range(21, 26):
                    for j in range(21, 26):
                        x[i, j] = 255
            
            elif pattern_type == 'copyright':
                trojan = cv2.imread('../watermark.png', cv2.IMREAD_GRAYSCALE)
                trojan = cv2.bitwise_not(trojan)
                trojan = cv2.resize(trojan, dsize=(28, 28), interpolation=cv2.INTER_CUBIC)
                x = x + trojan
                
            elif pattern_type == 'apple':
                trojan = cv2.imread('../apple.png', cv2.IMREAD_GRAYSCALE)
                trojan = cv2.bitwise_not(trojan)
                trojan = cv2.resize(trojan, dsize=(28, 28), interpolation=cv2.INTER_CUBIC)
                x = x + trojan
                
            elif pattern_type == 'vertical_line':
                start_idx = 5
                size = 5
                # vertical line  
                for i in range(start_idx, start_idx+size):
                    x[i, start_idx] = 255
                
                # horizontal line
                for i in range(start_idx-size//2, start_idx+size//2 + 1):
                    x[start_idx+size//2, i] = 255
            elif pattern_type == 'pixel':
                pattern_type = [[[0, 0], [0, 1], [0, 2], [0, 3]],
                [[0, 6], [0, 7], [0, 8], [0, 9]],
                [[3, 0], [3, 1], [3, 2], [3, 3]],
                [[3, 6], [3, 7], [3, 8], [3, 9]]]
                for i in range(len(pattern_type)):
                    for j in range(len(pattern_type[i])):
                        pos = pattern_type[i][j]
                        x[pos[0]][pos[1]] = 1

    if mode == 'DBA':
        if dataset == 'cifar10' or dataset == 'tiny-imagenet':
            if pattern_type == 'vertical_line':
                if agent_idx % 4 == 0:
                    for d in range(0, 3):  
                        for i in range(start_idx, start_idx+(size//2)+1):
                            x[i, start_idx][d] = 0
                            
                #lower part of vertical
                elif agent_idx % 4 == 1:
                    for d in range(0, 3):  
                        for i in range(start_idx+(size//2)+1, start_idx+size+1):
                            x[i, start_idx][d] = 0
                            
                #left-part of horizontal
                elif agent_idx % 4 == 2:
                    for d in range(0, 3):  
                        for i in range(start_idx-size//2, start_idx+size//4 + 1):
                            x[start_idx+size//2, i][d] = 0
                            
                #right-part of horizontal
                elif agent_idx % 4 == 3:
                    for d in range(0, 3):  
                        for i in range(start_idx-size//4+1, start_idx+size//2 + 1):
                            x[start_idx+size//2, i][d] = 0

            elif pattern_type == 'pixel':
                pattern_type = [[[0, 0], [0, 1], [0, 2], [0, 3]],
                [[0, 6], [0, 7], [0, 8], [0, 9]],
                [[3, 0], [3, 1], [3, 2], [3, 3]],
                [[3, 6], [3, 7], [3, 8], [3, 9]]]

                i = agent_idx % 4
                for d in range(0, 3):
                    for j in range(len(pattern_type[i])):
                            pos = pattern_type[i][j]
                            x[pos[0]][pos[1]][d] = 1

        elif dataset == 'mnist':
            if pattern_type == 'pixel':
                    pattern_type = [[[0, 0], [0, 1], [0, 2], [0, 3]],
                    [[0, 6], [0, 7], [0, 8], [0, 9]],
                    [[3, 0], [3, 1], [3, 2], [3, 3]],
                    [[3, 6], [3, 7], [3, 8], [3, 9]]]

                    i = agent_idx % 4
                    for j in range(len(pattern_type[i])):
                            pos = pattern_type[i][j]
                            x[pos[0]][pos[1]] = 1
    x = x.reshape(original_shape)
    return x

def get_gradient_of_model(model):
    size = 0
    for layer in model.parameters():
        grad = layer.grad
        size += grad.view(-1).shape[0]
    sum_var = torch.FloatTensor(size).fill_(0)

    size = 0
    for layer in model.parameters():
        grad = layer.grad
        sum_var[size:size + grad.view(-1).shape[0]] = (
                grad).view(-1)
        size += grad.view(-1).shape[0]
    return sum_var
    
def get_gradient_of_model(model):
    size = 0
    for layer in model.parameters():
        grad = layer.grad
        size += grad.view(-1).shape[0]
    sum_var = torch.FloatTensor(size).fill_(0)
    
    size = 0
    for layer in model.parameters():
        grad = layer.grad
        sum_var[size:size + grad.view(-1).shape[0]] = (
                grad).view(-1)
        size += grad.view(-1).shape[0]
    return sum_var

def norm_between_two_vector(vector1, vector2, norm = 2):
    return torch.norm(vector1 - vector2, norm)

def cosine_simi_between_two_vector(vector1, vector2):
    criterion = torch.cosine_similarity()
    return 1 - criterion(vector1, vector2)

def get_classification_model(args):
    if args.data == 'mnist':
        from classifier_models import mnist_basicnet
        def create_net():
            return mnist_basicnet.CNN_MNIST() 

    elif args.clsmodel == 'vgg11':
        from classifier_models import vgg
        def create_net():
            if args.data == 'tiny-imagenet':
                return vgg.VGG('VGG11', num_classes=args.num_classes, feature_dim=2048)
            else:
                return vgg.VGG('VGG11', num_classes=args.num_classes)
        
        
    elif args.clsmodel == 'PreActResNet18':
        from classifier_models import PreActResNet18
        def create_net():
            return PreActResNet18(num_classes=args.num_classes)
        
    elif args.clsmodel == 'ResNet18':
        from classifier_models import ResNet18
        def create_net():
            return ResNet18()
        
    elif args.clsmodel == 'ResNet18TinyImagenet':
        from classifier_models import ResNet18TinyImagenet
        def create_net():
            return ResNet18TinyImagenet()
    
    clsmodel = create_net().to(args.device)

    return clsmodel

def print_exp_details(args):
    print('======================================')
    print(f'    Dataset: {args.data}')
    print(f'    Global Rounds: {args.rounds}')
    print(f'    Aggregation Function: {args.aggr}')
    print(f'    Number of agents: {args.num_agents}')
    print(f'    Fraction of agents: {args.agent_frac}')
    print(f'    Batch size: {args.bs}')
    print(f'    Client_LR: {args.client_lr}')
    print(f'    Server_LR: {args.server_lr}')
    print(f'    Client_Momentum: {args.client_moment}')
    print(f'    RobustLR_threshold: {args.robustLR_threshold}')
    print(f'    Noise Ratio: {args.noise}')
    print(f'    Number of corrupt agents: {args.num_corrupt}')
    print(f'    Poison Frac: {args.poison_frac}')
    print(f'    Clip: {args.clip}')
    print('======================================')
    