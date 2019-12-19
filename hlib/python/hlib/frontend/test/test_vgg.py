from test_wrapper import *
from hlib.frontend import relay_parser
import sys
import numpy as np
import keras
sys.trackbacklimit = 0

batch=1
data_path = "/home/pbc48/install/datasets/imagenet_numpy/images/val/"
x_test = np.load(data_path+"x_test.npy")
y_test = np.load(data_path+"y_test.npy")
print(x_test.shape)
print(y_test.shape)
keras_model = keras.applications.VGG16(include_top=True, weights='imagenet',
        input_shape=(224, 224, 3), classes=1000)
x = x_test
#x = x_train[0:49984,0:32,0:32,0:3]/255#.reshape(-1, 32,32,32,3)#.transpose(0,1,4,2,3)
x_keras=np.reshape(x,(-1,batch,224,224,3))
x=np.transpose(x_keras,[0,1,4,2,3])
x= np.reshape(x,(-1,batch,3,224,224))
y = y_test.reshape(-1,batch)
x = x[0:100]
y = y[0:100]
test = 1
if(test == 0):
    test_wrapper(keras_model, "relay", "keras", "VGG16",
                 x, y, (batch, 1000), {'input_1': (batch,3,224,224)}, batch_size=batch)
elif(test == 1):
    correct = 0
    total   = 0
    for i in range(y.shape[0]):
        x_p = keras_model.predict(x_keras[i])
        if(np.argmax(x_p,axis=1)==y[i]):
            correct+=1
        total+=1
    print("accuracy:",correct/(total*1.0))
