import argparse
import torch

def args_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attack_mode', type=str, default='None',
                        help="DBA, trigger_generation, normal")

    parser.add_argument('--clsmodel', type=str, default='vgg11',
                        help="vgg11, PreActResNet18, ResNet18, ResNet18TinyImagenet")

    parser.add_argument('--attack_start_round', type=float, default=0, help='when to start attack epoch')

    parser.add_argument('--noise_eps', type=float, default=0.3, help='epsilon for data poisoning')

    parser.add_argument('--alpha', type=float, default=0.5, help='alpha between two loss')

    parser.add_argument('--noise_total_epoch', type=int, default=1,
                        help="total epoch for noise training")

    parser.add_argument('--noise_sub_epoch', type=int, default=1,
                        help="competitive round inside one epoch for noise_training")

    parser.add_argument('--beta', type=float, default=0.5, help='beta for direcht ditribution of non iid data')

    parser.add_argument('--data', type=str, default='fmnist',
                        help="dataset we want to train on")

    parser.add_argument('--poison_mode', type=str, default='all2one',
                        help="all2one, one2one, all2all")

    parser.add_argument('--num_agents', type=int, default=10,
                        help="number of agents:K")
    
    parser.add_argument('--agent_frac', type=float, default=1,
                        help="fraction of agents per round:C")
    
    parser.add_argument('--num_corrupt', type=int, default=0,
                        help="number of corrupt agents")
    
    parser.add_argument('--rounds', type=int, default=200,
                        help="number of communication rounds:R")
    
    parser.add_argument('--aggr', type=str, default='avg', 
                        help="aggregation function to aggregate agents' local weights")
    
    parser.add_argument('--local_ep', type=int, default=2,
                        help="number of local epochs:E")
    
    parser.add_argument('--bs', type=int, default=256,
                        help="local batch size: B")
    
    parser.add_argument('--client_lr', type=float, default=0.1,
                        help='clients learning rate')

    parser.add_argument('--generator_lr', type=float, default=1e-4,
                        help='learning rate of noise generator of malicious client')

    parser.add_argument('--client_moment', type=float, default=0.9,
                        help='clients momentum')
    
    parser.add_argument('--server_lr', type=float, default=1,
                        help='servers learning rate for signSGD')
    
    parser.add_argument('--base_class', type=int, default=5, 
                        help="base class for backdoor attack")
    
    parser.add_argument('--target_class', type=int, default=7, 
                        help="target class for backdoor attack")
    
    parser.add_argument('--poison_frac', type=float, default=0.0, 
                        help="fraction of dataset to corrupt for backdoor attack")
    
    parser.add_argument('--pattern_type', type=str, default='pixel', 
                        help="shape of bd pattern, including:square, copyright, apple, vertical_line, apple")
    
    parser.add_argument('--robustLR_threshold', type=int, default=0, 
                        help="break ties when votes sum to 0")
    
    parser.add_argument('--clip', type=float, default=0, 
                        help="weight clip to -clip,+clip")
    
    parser.add_argument('--noise', type=float, default=0, 
                        help="set noise such that l1 of (update / noise) is this ratio. No noise if 0")
    
    parser.add_argument('--top_frac', type=int, default=100, 
                        help="compare fraction of signs")
    
    parser.add_argument('--snap', type=int, default=1,
                        help="do inference in every num of snap rounds")
       
    parser.add_argument('--device',  default=torch.device("cuda:0" if torch.cuda.is_available() else "cpu"), 
                        help="To use cuda, set to a specific GPU ID.")
    
    parser.add_argument('--num_workers', type=int, default=0, 
                        help="num of workers for multithreading")
    
    args = parser.parse_args()
    return args