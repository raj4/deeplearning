# Author: Raj Agrawal 

# Builds a 3D spatio-temporal convolutional neural network to detect texting and 
# driving from a video stream 

# Quick Architectural Overview:
# - 3 convolutional layers (ReLu, Dropout, MaxPooling), 2 dense layers
# - Binary Hinge-Loss  
# - Adam update  
# - Early Stopping 

# References: See paper. Special thanks to Daniel Nouri for his tutorial at 
# http://danielnouri.org/notes/category/machine-learning/ 

from __future__ import division 

import sys
import lasagne
import theano
import numpy as np
import cPickle as pickle

from lasagne.layers import InputLayer, DenseLayer, NonlinearityLayer, DropoutLayer
from lasagne.layers.dnn import Conv3DDNNLayer, MaxPool3DDNNLayer
from lasagne.objectives import binary_hinge_loss
from lasagne.updates import adam
from lasagne import layers

from nolearn.lasagne import NeuralNet
from nolearn.lasagne import BatchIterator
from nolearn.lasagne import PrintLayerInfo

from random_image_generator import * 

def float32(k):
    return np.cast['float32'](k)

def build_layers():  
    """
    Builds layers for a 3D spatio-temporal CNN 
    Returns
    -------
    list
        A list containing the network layers, where the output layer is at key 'output'
    """
    layers=[
        ('input', InputLayer),
        ('conv1', Conv3DDNNLayer),
        ('pool1', MaxPool3DDNNLayer),
        ('dropout1', DropoutLayer),  
        ('conv2', Conv3DDNNLayer),
        ('pool2', MaxPool3DDNNLayer),
        ('dropout2', DropoutLayer),  
        ('conv3', Conv3DDNNLayer),
        ('pool3', MaxPool3DDNNLayer),
        ('dropout3', DropoutLayer),  
        ('hidden4', DenseLayer),
        ('dropout4', DropoutLayer),  
        ('hidden5', DenseLayer),
        ('output', DenseLayer),
        ]
    return layers

# Did not use - if want to use Nesterov update w/ linearly decaying learning 
# rate use this class - see tutorial at top for details  
class AdjustVariable(object):
    """
    Class controlling how to tune the momentum and learning rate
    """
    def __init__(self, name, start=0.03, stop=0.001):
        self.name = name
        self.start, self.stop = start, stop
        self.ls = None

    def __call__(self, nn, train_history):
        if self.ls is None:
            self.ls = np.linspace(self.start, self.stop, nn.max_epochs)

        epoch = train_history[-1]['epoch']
        new_value = float32(self.ls[epoch - 1])
        getattr(nn, self.name).set_value(new_value)

class FlipBatchIterator(BatchIterator):
    """
    Note: Did not alter intensity values b/c already did that (1.5x increase of
          raw data size by artifically adding modified intensity values)
    """ 
    def transform(self, Xb, yb):
        Xb, yb = super(FlipBatchIterator, self).transform(Xb, yb)

        # Distort half of the images in this batch at random:
        bs = Xb.shape[0]
        num_changes = int(bs * .75)
        indices = np.random.choice(bs, num_changes, replace=False)
        distorts_per_cat = int(len(indices) / 2)
        flip_indcs = indices[0:distorts_per_cat]
        rotate_indcs = indices[distorts_per_cat:(2*distorts_per_cat)]
        Xb[flip_indcs] = Xb[flip_indcs, :, :, ::-1] #Verify good flip 
        for i in rotate_indcs:
            Xb[i, :, :, :, :] = random_image_generator(Xb[i, :, :, :, :])
        return Xb, yb

class EarlyStopping(object):
    """
    """
    def __init__(self, patience=100):
        self.patience = patience
        self.best_valid = np.inf
        self.best_valid_epoch = 0
        self.best_weights = None
        self.num_epochs = 0 

    def __call__(self, nn, train_history):
        current_valid = train_history[-1]['valid_loss']
        current_epoch = train_history[-1]['epoch']
        self.num_epochs += 1 

        # Save weights every 20 epochs to server (transport to s3 eventually)
        if self.num_epochs % 20 == 0:
            weights = nn.get_all_params_values()
            weight_path = '../data/train/weights/cnn' + str(self.num_epochs)
            with open(weight_path, 'wb') as f:
                pickle.dump(weights, f, -1)

        # Update pointer if there are better weights 
        if current_valid < self.best_valid:
            self.best_valid = current_valid
            self.best_valid_epoch = current_epoch
            self.best_weights = nn.get_all_params_values()
        
        # Seems like we might be starting to overfit, stop updating   
        elif self.best_valid_epoch + self.patience < current_epoch:
            print("Early stopping.")
            print("Best valid loss was {:.6f} at epoch {}.".format(
                self.best_valid, self.best_valid_epoch))
            nn.load_params_from(self.best_weights)
            raise StopIteration()
 
# Build CNN

layers = build_layers()

network = NeuralNet(
    layers=layers,
    input_shape = (None, 1, 10, 81, 144), #Batch size of 32 
    conv1_num_filters=16, conv1_filter_size=(3, 3, 3), pool1_pool_size=(1, 2, 2),
    dropout1_p=0.1, 
    conv2_num_filters=32, conv2_filter_size=(3, 3, 3), pool2_pool_size=(2, 2, 2),
    dropout2_p=0.2,  
    conv3_num_filters=64, conv3_filter_size=(3, 3, 3), pool3_pool_size=(1, 2, 2),
    dropout3_p=0.3,  
    hidden4_num_units=500,
    dropout4_p=0.5,  
    hidden5_num_units=500,
    output_num_units=1, output_nonlinearity=None,
    
    update=adam,
    objective_loss_function=binary_hinge_loss,
    
    regression=False,
    batch_iterator_train=FlipBatchIterator(batch_size=32, shuffle=False), #Data already shuffled 
    on_epoch_finished=[
        EarlyStopping(patience=200) #If want to update learning rate, put here 
        ],
    max_epochs=10000,
    verbose=1
)

# Uncomment if you want to see network's final dimensions 

# network.initialize()
# layer_info = PrintLayerInfo()
# layer_info(network)

if __name__ == '__main__':

    # Large network, need to increase Python's recursion limit
    sys.setrecursionlimit(10000)

    # Load data (did not standardize b/c images in 0-256)
    X = np.load('../data/train/images_by_time_mat.npy')
    X = X.astype(np.float32)
    X.shape = (3064, 1, 10, 81, 144) # FIX hardcoded - make general  

    # Only have 1 channel, need to reshape in order to match 5d required input 
    
    Y = np.load('../data/train/labels.npy')

    # Shuffle data (already shuffled before. if not uncomment)
    # num_samps = X.shape[0]
    # indcs = np.arange(num_samps)
    # np.random.shuffle(indcs)
    # X = X[indcs]
    # Y = Y[indcs]

    # Convert Y into a binary vector 
    # 0 means nothing, 1 only driver text, 2 both text, 3 only passanger text
    Y[Y == 0] = -1
    Y[Y == 1] = 1
    Y[Y == 2] = 1 #1466 total 1s 
    Y[Y == 3] = -1 #1598 total -1s 
    Y = Y.astype(np.int32)

    # Fit model 
    network.fit(X, Y)

    # Save Model 
    with open('../model/network.pickle', 'wb') as f:
        pickle.dump(network, f, -1)
