import keras
from keras.layers import Conv2D, Activation, MaxPooling2D, Dropout, Dense, Flatten
import numpy as np
import heterocl as hcl
import tvm
from tvm import relay
import tvm.relay.frontend as relay_front
import numpy.testing as tst
from frontend.relay_parser import relay_parser, get_relay_model
import hlib
#import pdb; pdb.set_trace()
num_classes=10
hcl.init(hcl.Float())
def verify_keras_frontend(keras_model, need_trans_before=True,need_trans_after=True,dtype='float32',test_name=""):
    assert(keras.backend.backend() == 'tensorflow')
    if(keras_model==None):
        return
    in_shapes = []
    for layer in keras_model._input_layers:
        in_shapes.append(tuple(dim.value if dim.value is not None else 1 for dim in layer.input.shape))

    def get_keras_output(xs, dtype='float32'):
        return keras_model.predict(xs)

    def get_hcl_output(xs, dtype='float32'):
        shape_dict = {name: x.shape for (name, x) in zip(keras_model.input_names, xs)}
        #return relay_front.from_keras(keras_model, shape_dict)
        return get_relay_model(keras_model, shape_dict, 'keras')

    def to_channels_first(arr):
        if(len(arr.shape)>1):
            return arr.transpose([0, -1] + list(range(1, arr.ndim - 1)))
        else:
            return arr

    def to_channels_last(arr):
        if(len(arr.shape)>1):
            return arr.transpose([0] + list(range(2, arr.ndim)) + [1])
        else:
            return arr

    xs = [np.random.randint(size=shape, low=1, high=10).astype(dtype) for shape in in_shapes]
    keras_out = get_keras_output(xs,dtype)
    print(len(keras_out))
    inputs = [to_channels_first(x) for x in xs] if need_trans_before else xs
    f,params = get_hcl_output(inputs,dtype)
    out = []
    if(isinstance(keras_out,(tuple,list))):
        for k_out in keras_out:
            out.append(hcl.asarray(np.zeros(k_out.shape)))
    else:
        out.append(hcl.asarray(np.zeros(keras_out.shape)))
    for i in range(len(inputs)):
        inputs[i] = hcl.asarray(inputs[i])
    for _in in inputs:
        print(_in.shape)
    if(test_name=="lstm"):
        params = [params[2],params[1],params[3],params[4],params[0]]
    if(test_name=="rnn"):
        params = [params[1],params[3],params[0],params[2]]
    for par in params:
        print(par.shape)
    for _out in out:
        print(_out.shape)
    f(*inputs,*params,*out)
    if(isinstance(keras_out,(tuple,list))):
        for i in range(len(keras_out)):
            if(need_trans_after):
                h_out = out[i].asnumpy()
                print(h_out)
                print(keras_out)
                print(np.max(h_out-keras_out))
                tst.assert_almost_equal(np.reshape(np.transpose(out[i].asnumpy(),(0,1,3,2)),keras_out[i].shape),keras_out[i],10**-6)
            else:
                h_out = out[i].asnumpy()
                print(h_out)
                print(keras_out[i])
                print(np.max(h_out-keras_out[i]))
                tst.assert_almost_equal(h_out,keras_out[i],10**-6)
    else:
        for i in range(len(inputs)):
            print(inputs[i])
        if(need_trans_after):
            shape = out[0].shape
            h_out = np.reshape(out[0].asnumpy(),(shape[0],shape[3],shape[1],shape[2]))
            h_out = np.transpose(h_out,[0,2,3,1])
            print(h_out)
            print(keras_out)
            print(np.max(h_out-keras_out))
            tst.assert_almost_equal(h_out,keras_out,10**-9)
        else:
            shape=out[0].shape
            h_out = out[0].asnumpy()
            print(h_out)
            print(keras_out)
            print(np.max(h_out-keras_out))
            tst.assert_almost_equal(h_out,keras_out,10**-9)

def merge_test(shape):
    x = keras.layers.Input(shape=shape)
    y = keras.layers.Input(shape=shape)
    z = keras.layers.Input(shape=shape)
    merge_funcs = [keras.layers.Add(),
                   #keras.layers.Subtract(),
                   keras.layers.Multiply(),
                   keras.layers.Maximum(),#,
                   #keras.layers.Average(),
                   keras.layers.Concatenate(axis=-1)]
    for merge_func in merge_funcs:
        if isinstance(merge_func, (keras.layers.merge.Subtract, keras.layers.merge.Dot)):
            out = merge_func([x, y])
        else:
            out = merge_func([x, y, z])
        keras_model = keras.models.Model([x,y,z], out)
        verify_keras_frontend(keras_model,False,False)   

def merge_2_test(shape):
    x = keras.layers.Input(shape=shape)
    y = keras.layers.Input(shape=shape)
    merge_funcs = [keras.layers.Subtract(),
                   keras.layers.Average()]
    for merge_func in merge_funcs:
        out = merge_func([x, y])
        keras_model = keras.models.Model([x,y], out)
        verify_keras_frontend(keras_model,False,False)   

def merge_conv_test():
    data = keras.layers.Input(shape=(3,3,2))
    x = keras.layers.Conv2D(4, (3, 3), padding="same")(data)
    y = keras.layers.Conv2D(4, (3, 3), padding="same")(data)
    z = keras.layers.Conv2D(4, (3, 3), padding="same")(data)
    merge_funcs = [keras.layers.Add(),
                   keras.layers.Subtract(),
                   keras.layers.Multiply(),
                   keras.layers.Maximum(),
                   keras.layers.Average(),
                   keras.layers.Concatenate()]
    for merge_func in merge_funcs:
        if isinstance(merge_func, (keras.layers.merge.Subtract, keras.layers.merge.Dot)):
            out = merge_func([x, y])
        else:
            out = merge_func([x, y, z])
    #out = keras.layers.Add()([x,y])
    keras_model = keras.models.Model(data, out)
    verify_keras_frontend(keras_model,True,True)

def pooling_test(shape):
    data = keras.layers.Input(shape=shape)
    x = keras.layers.MaxPooling2D()(data)
    y = keras.layers.MaxPooling2D()(x)
    z = keras.layers.AveragePooling2D()(y)
    w = keras.layers.AveragePooling2D()(z)
    keras_model = keras.models.Model(data, w)
    verify_keras_frontend(keras_model) 

def batch_norm_test(shape,axis):
    data = keras.layers.Input(shape=shape)
    x = keras.layers.BatchNormalization(axis=axis+1)(data)
    y = keras.layers.BatchNormalization(axis=axis+1)(x)
    keras_model = keras.models.Model(data, y)
    verify_keras_frontend(keras_model,False,False)

def merge_and_pool_test(shape):
    data = keras.layers.Input(shape=shape)
    x = keras.layers.MaxPooling2D()(data)
    w = keras.layers.MaxPooling2D()(x)
    y = keras.layers.AveragePooling2D()(data)
    z = keras.layers.AveragePooling2D()(y)
    out = keras.layers.Add()([w,z])
    keras_model = keras.models.Model(data, out)
    verify_keras_frontend(keras_model,True,True) 

def merge_out_tup_test(shape):
    data = keras.layers.Input(shape=shape)
    x = keras.layers.MaxPooling2D()(data)
    z = keras.layers.MaxPooling2D()(x)
    y = keras.layers.AveragePooling2D()(data)
    w = keras.layers.AveragePooling2D()(y)
    keras_model = keras.models.Model(data, [z,w])
    verify_keras_frontend(keras_model)

def merge_just_conv_test():
    data = keras.layers.Input(shape=(4,4,3))
    out = keras.layers.Conv2D(3, (2, 2), padding="same",bias=False)(data)
    keras_model = keras.models.Model(data, out)
    #keras_model.layers[1].set_weights(np.ones((1,2,2,3,3)))
    verify_keras_frontend(keras_model,True,True)

def dot_test():
    data1 = keras.layers.Input(shape=(2, 2))
    data2 = keras.layers.Input(shape=(2, 2))
    merge_funcs = [keras.layers.Dot(axes=[1, 2]),
                   keras.layers.Dot(axes=[2, 1]),
                   keras.layers.Dot(axes=[1, 1]),
                   keras.layers.Dot(axes=[2, 2]),
                   keras.layers.Dot(axes=1),
                   keras.layers.Dot(axes=2)]
    for merge_func in merge_funcs:
        out = merge_func([data1, data2])
        keras_model = keras.models.Model([data1, data2], out)
        verify_keras_frontend(keras_model)

def sequential_test():
    keras_model = keras.models.Sequential([
        keras.layers.Dense(16, input_dim=32, activation='relu'),
        keras.layers.Dropout(0.5),
        keras.layers.Dense(8, activation='relu'),
        keras.layers.Dropout(0.5),
        keras.layers.Dense(1, activation='sigmoid')
    ])
    verify_keras_frontend(keras_model,False,False)

def simple_pool_test():
    data = keras.layers.Input(shape=(9, 9, 3))
    # maxpool
    x = keras.layers.MaxPooling2D((3, 3), strides=(1, 1), padding='same')(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,need_trans_before=True,need_trans_after=True)
    # avgpool
    y = keras.layers.AveragePooling2D(pool_size=(3, 3), strides=(1,1), padding='valid')(data)
    keras_model = keras.models.Model(data, y)
    verify_keras_frontend(keras_model,need_trans_before=True,need_trans_after=True)

def reshape_test():
    # input_shape len is 3, target_shape len is 3
    data = keras.layers.Input(shape=(32, 32, 3))
    x = keras.layers.Reshape(target_shape=(16, 64, 3))(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,False,False)
    # input_shape len is 3, target_shape len is 2
    data = keras.layers.Input(shape=(32, 8, 3))
    x = keras.layers.Reshape(target_shape=(256, 3))(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,False,False)
    # input_shape len is 2, target_shape len is 3
    data = keras.layers.Input(shape=(256, 3))
    x = keras.layers.Reshape(target_shape=(8, 32, 3))(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,False,False)
    # input_shape len is 2, target_shape len is 1
    data = keras.layers.Input(shape=(2, 8))
    x = keras.layers.Reshape(target_shape=(16,))(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,False,False)
    # input_shape len is 1, target_shape len is 2
    data = keras.layers.Input(shape=(16,))
    x = keras.layers.Reshape(target_shape=(4, 4))(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,False,False)
    # input_shape len is 2, target_shape len is 2
    data = keras.layers.Input(shape=(2, 8))
    x = keras.layers.Reshape(target_shape=(4, 4))(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,False,False)

def rnn_test():
    data = keras.layers.Input(shape=(1, 32))
    names = ["lstm","rnn","gru"]
    i=0
    rnn_funcs = [keras.layers.LSTM(units=16, return_state=False,
                    recurrent_activation='sigmoid', activation='tanh'),
                 keras.layers.SimpleRNN(units=16, return_state=False,
                    activation='tanh'),
                 keras.layers.GRU(units=16, return_state=False,
                    recurrent_activation='sigmoid', activation='tanh')]
    for rnn_func in rnn_funcs:
        x = rnn_func(data)
        keras_model = keras.models.Model(data, x)
        verify_keras_frontend(keras_model,False,False,test_name=names[i])
        i+=1

def dense_test():
    data = keras.layers.Input(shape=(32, 32, 1))
    x = keras.layers.Flatten()(data)
    #x = keras.layers.Dropout(0.5)(x)
    x = keras.layers.Dense(10, activation='relu', kernel_initializer='uniform')(x)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,False,False)

def conv_code_test():
    input_1 = hcl.placeholder(shape=(1,3,3,3))
    param_1 = hcl.placeholder(shape=(3,3,3,3))
    param_2 = hcl.placeholder(shape=(3,))
    padding=[]
    strides=[]
    dilation=[]
    axis=1
    for i in range(2):
        padding.append(tvm.expr.IntImm(dtype='int64',value=1))
        strides.append(tvm.expr.IntImm(dtype='int32',value=1))
        dilation.append(tvm.expr.IntImm(dtype='int32',value=1))
    def func(_in,filt,bias):
        i_0 = hlib.nn.conv2d(_in,filt,padding=padding,
        strides=strides,dilation=dilation)
        return hlib.nn.bias_add(i_0,bias,axis=axis)
    s = hcl.create_schedule([input_1,param_1,param_2],func)
    print(hcl.lower(s))
    f = hcl.build(s)
    _in = hcl.asarray(np.random.randint(10,size=(1,3,3,3)))
    filt = hcl.asarray(np.random.randint(10,size=(3,3,3,3)))
    bias = hcl.asarray(np.random.randint(10,size=(3,)))
    out = hcl.asarray(np.zeros((1,3,3,3)))
    f(_in,filt,bias,out)
    print(out.asnumpy())

def test_forward_multi_inputs():
    data1 = keras.layers.Input(shape=(32, 32, 3))
    data2 = keras.layers.Input(shape=(32, 32, 3))
    x = keras.layers.Conv2D(8, (3, 3), padding="same")(data1)
    y = keras.layers.Conv2D(8, (3, 3), padding="same")(data2)
    z = keras.layers.Average()([x, y])
    z = keras.layers.GlobalAveragePooling2D()(z)
    keras_model = keras.models.Model([data1, data2], z)
    verify_keras_frontend(keras_model,True,True)

def test_forward_multi_outputs():
    data = keras.layers.Input(shape=(32, 32, 3))
    x = keras.layers.Conv2D(8, (3, 3), padding="same")(data)
    x = keras.layers.GlobalAveragePooling2D()(x)
    y = keras.layers.Conv2D(8, (3, 3), padding="same")(data)
    y = keras.layers.GlobalAveragePooling2D()(y)
    z = keras.layers.Conv2D(8, (3, 3), padding="same")(data)
    z = keras.layers.GlobalMaxPooling2D()(z)
    w = keras.layers.Conv2D(8, (3, 3), padding="same")(data)
    w = keras.layers.GlobalMaxPooling2D()(w)
    keras_model = keras.models.Model(data, [x, y, z, w])
    verify_keras_frontend(keras_model,True,False)

def test_reuse_layers():
    # reuse conv2d
    data = keras.layers.Input(shape=(32, 32, 3))
    conv2d = keras.layers.Conv2D(8, (3, 3), padding="same")
    x = conv2d(data)
    y = conv2d(data)
    z = keras.layers.Add()([x, y])
    z = keras.layers.GlobalAveragePooling2D()(z)
    keras_model = keras.models.Model(data, z)
    verify_keras_frontend(keras_model,True,False)
    # reuse add
    data = keras.layers.Input(shape=(32, 32, 3))
    x = keras.layers.Conv2D(8, (3, 3), padding="same")(data)
    add = keras.layers.Add()
    x = add([x, x])
    x = add([x, x])
    z = keras.layers.GlobalAveragePooling2D()(x)
    keras_model = keras.models.Model(data, z)
    verify_keras_frontend(keras_model,True,False)

def test_multiple_reuse():
    in1 = keras.layers.Input((4,3,3))
    act0 = keras.layers.Activation('sigmoid')(in1)
    act1 = keras.layers.ReLU()(act0)
    add1 = keras.layers.Add()([act0,act1])
    act2 = keras.layers.ReLU()(add1)
    add2 = keras.layers.Add()([act1,act2])
    add3 = keras.layers.Add()([act1,add2])
    keras_model = keras.models.Model(in1,add3)
    verify_keras_frontend(keras_model,False,False)

def test_forward_conv():
    data = keras.layers.Input(shape=(4, 4, 2))
    conv_funcs = [keras.layers.Conv2D(filters=10, kernel_size=(3, 3),
                                      strides=(2, 2), padding='same'),
                  keras.layers.Conv2D(filters=10, kernel_size=(3, 3),
                                      dilation_rate=(2, 2), padding='same'),
                  keras.layers.Conv2D(filters=1, kernel_size=(3, 3), padding='same'),
                  keras.layers.DepthwiseConv2D(kernel_size=(3, 3), padding='same'),
                  #keras.layers.Conv2DTranspose(filters=10, kernel_size=(3, 3), padding='valid'),
                  keras.layers.SeparableConv2D(filters=10, kernel_size=(3, 3), padding='same')]
    for conv_func in conv_funcs:
        print(conv_func)
        x = conv_func(data)
        keras_model = keras.models.Model(data, x)
        verify_keras_frontend(keras_model,True,True)

def test_depthwise_conv():
    data = keras.layers.Input(shape=(4, 4, 3))
    x = keras.layers.DepthwiseConv2D(kernel_size=(3, 3), padding='same')(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,True,True)

def test_separable_conv():
    data = keras.layers.Input(shape=(4, 4, 3))
    x = keras.layers.DepthwiseConv2D(kernel_size=(3, 3), padding='same')(data)
    keras_model = keras.models.Model(data, x)
    verify_keras_frontend(keras_model,True,True)

def test_forward_activations():
    data = keras.layers.Input(shape=(8,3,3))
    act_funcs = [keras.layers.Activation('softmax'),
                 keras.layers.Softmax(),
                 keras.layers.Softmax(axis=-1),
                 keras.layers.Softmax(axis=1),
                 keras.layers.Softmax(axis=2),
                 keras.layers.Softmax(axis=3),
                 keras.layers.Activation('softplus'),
                 keras.layers.Activation('relu'),
                 keras.layers.Activation('softsign'),
                 keras.layers.Activation('hard_sigmoid'),
                 keras.layers.Activation('sigmoid'),
                 keras.layers.Activation('tanh'),
                 keras.layers.Activation('linear'),
                 keras.layers.Activation('selu'),
                 keras.layers.ReLU(),
                 keras.layers.ReLU(max_value=6.),
                 keras.layers.ReLU(max_value=6., threshold=0.),
                 keras.layers.ReLU(max_value=6., threshold=1.),
                 keras.layers.ReLU(max_value=6., threshold=1., negative_slope=0.),
                 keras.layers.ReLU(max_value=6., threshold=1., negative_slope=0.5),
                 keras.layers.ReLU(max_value=6., threshold=1., negative_slope=1.),
                 keras.layers.LeakyReLU(alpha=0.3),
                 keras.layers.PReLU(weights=np.random.rand(1, 32, 32, 3)),
                 keras.layers.ELU(alpha=0.5),
                 keras.layers.ThresholdedReLU(theta=0.5)]
    for act_func in act_funcs:
        x = act_func(data)
        keras_model = keras.models.Model(data, x)
        verify_keras_frontend(keras_model,False,False)


def cifar10_test():
    model = keras.models.Sequential()
    model.add(Conv2D(32, (3, 3), padding='same',
                    input_shape=(16,16,3)))
    model.add(Activation('relu'))
    model.add(Conv2D(32, (3, 3)))
    model.add(Activation('relu'))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Dropout(0.25))

    model.add(Conv2D(64, (3, 3), padding='same'))
    model.add(Activation('relu'))
    model.add(Conv2D(64, (3, 3)))
    model.add(Activation('relu'))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Dropout(0.25))

    model.add(Flatten())
    model.add(Dense(512))
    model.add(Activation('relu'))
    model.add(Dropout(0.5))
    model.add(Dense(num_classes))
    model.add(Activation('softmax'))

    input_layer = keras.layers.Input(batch_shape=model.layers[0].input_shape)
    prev_layer = input_layer
    for layer in model.layers:
        prev_layer = layer(prev_layer)

    model = keras.models.Model([input_layer], [prev_layer])
    verify_keras_frontend(model,True,False)

def test_forward_vgg16():
    keras_model = keras.applications.VGG16(include_top=True, weights='imagenet',
        input_shape=(224, 224, 3), classes=1000)
    verify_keras_frontend(keras_model,True,False)

def test_forward_xception():
    keras_model = keras.applications.Xception(include_top=True, weights='imagenet',
        input_shape=(299, 299, 3), classes=1000)
    print(keras_model.summary())
    verify_keras_frontend(keras_model)


def test_forward_resnet50():
    keras_model = keras.applications.ResNet50(include_top=True, weights='imagenet',
        input_shape=(224, 224, 3), classes=1000)
    print(keras_model.summary())
    verify_keras_frontend(keras_model,True,False)


def test_forward_mobilenet():
    keras_model = keras.applications.MobileNet(include_top=True, weights='imagenet',
        input_shape=(224, 224, 3), classes=1000)
    print(keras_model.summary())
    verify_keras_frontend(keras_model,True,False,'float64')

if __name__ == "__main__":
    #merge_test((2,2))
    #merge_test((10,7,4))
    #merge_2_test((3,3))
    #pooling_test((32,32,16))
    #pooling_test((32,16,32))
    #pooling_test((16,32,32))
    #dot_test()
    #sequential_test()
    #rnn_test()
    #reshape_test()
    #simple_pool_test()
    #merge_and_pool_test((16,8,4))
    #merge_and_pool_test((8,8,8))
    #merge_out_tup_test((4,4,4))
    #merge_just_conv_test()
    #test_forward_conv()
    #test_depthwise_conv()
    #test_separable_conv()
    #test_forward_multi_inputs()
    #test_forward_multi_outputs()
    #test_reuse_layers()
    #conv_code_test()
    #merge_conv_test()
    #dense_test()
    test_forward_activations()
    #cifar10_test()
    #test_forward_vgg16()
    #test_forward_xception()
    #test_forward_resnet50()
    #batch_norm_test((4,4),1)
    #test_forward_mobilenet()
    #test_multiple_reuse()
    print("All Passed!")