import numpy as np
import random
import math
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import scipy.optimize
from collections import namedtuple
from itertools import count
from environment import *
from gridmap import GridMap
from algorithm import *
import matplotlib.pyplot as plt
import copy 



Transition = namedtuple('Transition',
                        ('state', 'action', 'reward'))

class ReplayMemory:

    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def push(self, *args):
        """Saves a transition."""
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = Transition(*args)
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size):
        return random.sample(self.memory, batch_size)

    def __len__(self):
        return len(self.memory)


class DQN(nn.Module):
    # TODO implement q network
    def __init__(self, inputs, outputs, hidden):
        super(DQN, self).__init__()

        self.fc1 = nn.Linear(inputs, hidden)
        self.fc2 = nn.Linear(hidden,outputs)
        #self.bn2 = nn.BatchNorm1d(output)

    def forward(self, x):
        # TODO implement train
        x2 = F.relu(self.fc1(x))
        out = self.fc2(x2)
        return out


class DQN_Agent:
    def __init__(self, env, input_size, output_size, hidden_size, batch_size = 128, lr = 0.001, gamma = .999, eps_start = 0.9, 
                 eps_end = 0.05, eps_decay = 2500,  replay_capacity = 10000, num_save = 200, num_episodes = 10000, shared=False, training = False, load_file = None):
        self.env = env
        self.orig_env = copy.deepcopy(env)
        self.grid_map = env.grid_map
        self.cars = env.grid_map.cars
        self.num_cars = len(self.cars)
        self.passengers = env.grid_map.passengers
        self.num_passengers = len(self.passengers)
        self.input_size = input_size
        self.output_size = output_size
        self.hidden_size = hidden_size
        self.batch_size = batch_size
        self.gamma = gamma
        self.eps_start = eps_start
        self.eps_end = eps_end
        self.eps_decay = eps_decay
        self.replay_capacity = replay_capacity
        self.num_episodes = num_episodes
        self.steps_done = 0
        self.lr = lr
        self.shared = shared
        self.num_save = num_save
        self.training = training
        self.algorithm = PairAlgorithm()
        self.episode_durations = []
        self.loss_history = []
        
        self.memory = ReplayMemory(self.replay_capacity)
        
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        print("Device being used:", self.device)
        self.policy_net = DQN(self.input_size, self.output_size , self.hidden_size).to(self.device)
        
        
        if load_file:
            self.policy_net.load_state_dict(torch.load(load_file))
            self.policy_net.eval()
            self.load_file = "Trained_" + load_file
            print("Checkpoint loaded")
        else:
            if self.shared: 
                pre = "shared_"
            else:
                pre = "unshared_"
            
            self.load_file = pre + "model_num_cars_" + str(self.num_cars) + "_num_passengers_" + str(self.num_passengers) + \
                    "_num_episodes_" + str(self.num_episodes) + "_hidden_size_" + str(self.hidden_size) + ".pth"
            
        self.optimizer = optim.RMSprop(self.policy_net.parameters(), lr = self.lr)

        

    def select_action(self,state):
        #Select action with epsilon greedy
        sample = random.random()
        
        eps_threshold = self.eps_end + (self.eps_start - self.eps_end) * \
            math.exp(-1. * self.steps_done / self.eps_decay)

        self.steps_done += 1
        
        if not self.training:
            eps_threshold = 0.0

        if sample > eps_threshold:
            # Choose best action
            with torch.no_grad():
                
                self.policy_net.eval() 
                return self.policy_net(state).view(self.num_passengers, self.num_cars).max(1)[1].view(1,self.num_passengers)

        else:
            #Choose random action
            return torch.tensor([[random.randrange(self.num_cars) for car in range(self.num_passengers)]], device=self.device, dtype=torch.long)

            

    def random_action(self, state):
        return torch.tensor([[random.randrange(self.num_cars) for car in range(self.num_passengers)]], device=self.device, dtype=torch.long)
    
    
    def get_state(self):
        # Cars (px, py, 1=matched), Passengers(pickup_x, pickup_y, dest_x, dest_y, 1=matched)
        # Vector Size = 3*C + 5*P 
        cars = self.cars
        passengers = self.passengers

        # Encode information about cars
        cars_vec = np.zeros(2*len(cars))
        
        for i, car in enumerate(cars):    
            cars_vec[2*i: 2*i + 2]  = [car.position[0], car.position[1]]

        # Encode information about passengers
        passengers_vec = np.zeros(4*len(passengers))
        for i, passenger in enumerate(passengers):
            passengers_vec[4*i: 4*i + 4]  = [passenger.pick_up_point[0], passenger.pick_up_point[1],
                                             passenger.drop_off_point[0],passenger.drop_off_point[1]]

        return torch.tensor(np.concatenate((cars_vec, passengers_vec)), device= self.device, dtype=torch.float).unsqueeze(0)
    
    
    def train(self):
        
        duration_sum = 0.0
        
        for episode in range(self.num_episodes):
            
            self.reset() 
            #self.reset_orig_env()
            
            state = self.get_state()  
            
            #action = self.select_action(state)
            #action = self.random_action([state])
            action = [self.algorithm.greedy_fcfs(self.grid_map)]
            
            
            reward, duration = self.env.step(action, shared = self.shared)
            
            duration_sum += duration
            
            if self.training:
                self.memory.push(state, action, torch.tensor(reward, device = self.device, dtype=torch.float).unsqueeze(0))  
                self.optimize_model()

                        
            self.episode_durations.append(duration)
            
            if self.training:
                self.plot_durations("rl_shared")
                self.plot_loss_history("rl_shared")
            
            if self.training and episode % self.num_save == 0:
                torch.save(self.policy_net.state_dict(), "episode_" + str(episode) + self.load_file )
                print("Checkpoint saved")
            #self.plot_durations()
            #self.plot_loss_history()
                    
            print("Episode: ", episode)

           
        if self.training:
            torch.save(self.policy_net.state_dict(), self.load_file )
            print("Checkpoint saved")
            
        print("Average duration was ", duration_sum/self.num_episodes)
        print("Finished")  
            
    def reset(self):
        self.env.reset()
        self.grid_map = self.env.grid_map
        self.cars = self.env.grid_map.cars
        self.passengers = self.env.grid_map.passengers
        
    def reset_orig_env(self):

        self.env = copy.deepcopy(self.orig_env)
        self.grid_map = self.env.grid_map
        self.cars = self.env.grid_map.cars
        self.passengers = self.env.grid_map.passengers
        self.grid_map.init_zero_map_cost()

        

    def optimize_model(self):
        if len(self.memory) < self.batch_size:
            return
        
        transitions = self.memory.sample(self.batch_size)
        batch = Transition(*zip(*transitions))
    
        state_batch = torch.cat(batch.state)
        action_batch = torch.cat(batch.action)
        reward_batch = torch.cat(batch.reward)
        
        self.policy_net.train()
        state_action_values = self.policy_net(state_batch).view(self.batch_size, self.num_passengers, self.num_cars).gather(2,action_batch.unsqueeze(2)).squeeze()

        # Compute the expected Q values
        expected_state_action_values = reward_batch
        

        # Compute Huber loss
        loss = F.smooth_l1_loss(state_action_values, expected_state_action_values)


        self.loss_history.append(loss.item())

        # Optimize the model
        self.optimizer.zero_grad()
        loss.backward()
        
        for param in self.policy_net.parameters():
            param.grad.data.clamp_(-1, 1)
        self.optimizer.step()



    def plot_durations(self, filename):
        print("Saving durations plot ...")
        plt.figure(2)
        plt.clf()
        durations_t = torch.tensor(self.episode_durations, dtype=torch.float)
        plt.title('Episode Duration history')
        plt.xlabel('Episode')
        plt.ylabel('Duration')
        plt.plot(durations_t.numpy())
        np.save("Duration_"+filename, durations_t.numpy())
        plt.savefig("Durations_history_" + filename)
        
    def plot_loss_history(self, filename):
        print("Saving loss history ...")
        plt.figure(2)
        plt.clf()
        loss = torch.tensor(self.loss_history, dtype=torch.float)
        plt.title('Loss history')
        plt.xlabel('Episodes')
        plt.ylabel('Loss')
        plt.plot(self.loss_history)
        plt.savefig("Loss_history_" + filename)

if __name__ == '__main__':
    num_cars = 8
    num_passengers = 8
    
    grid_map = GridMap(1, (100,100), num_cars, num_passengers)
    cars = grid_map.cars
    passengers = grid_map.passengers
    env = Environment(grid_map)


    input_size = 2*num_cars + 4*num_passengers # cars (px, py), passengers(pickup_x, pickup_y, dest_x, dest_y)
    output_size = num_cars * num_passengers  # num_cars * (num_passengers + 1)
    hidden_size = 100
    load_file = "unshared_model_num_cars_3_num_passengers_3_num_episodes_100000_hidden_size_100.pth"
    load_file = None
    agent = DQN_Agent(env, input_size, output_size, hidden_size, load_file = load_file,lr=0.001, num_episodes=1000, shared = False, training = False)
    agent.train()
    # durations = np.load("Duration_rl_2.npy")
    # print(np.mean(durations[-2000:]))
    # print(durations[-10:])