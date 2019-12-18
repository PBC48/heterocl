import tvm
import keras
import tvm.relay.frontend as relay_front
import numpy as np
import heterocl as hcl
import hlib
import re
from .utils import *
#from copy import deepcopy
from tvm.relay.expr import Function, Var, Call, Let, If, Constant
from tvm.relay.expr import TupleGetItem, Tuple
from tvm.relay.ty import TensorType, TupleType

# Exploring the AST here
hcl.init(hcl.Float())
# move this to different file
_convert_map = {
    'nn.dense': hlib.op.nn.dense,
    'nn.relu': hlib.op.nn.relu,
    'nn.bias_add': hlib.op.nn.bias_add,
    #    'prelu'                   : 'hlib.nn.prelu',
    'tanh': hlib.op.math.tanh,
    'sigmoid': hlib.op.math.sigmoid,
    'nn.softmax': hlib.op.nn.softmax,
    'nn.leaky_relu': hlib.op.nn.leakyrelu,
    'exp': hlib.op.math.exp,
    'log': hlib.op.math.log,
    'sqrt': hlib.op.math.sqrt,
    'clip': hlib.op.math.clip,
    'cast': hlib.op.op.cast,
    'nn.conv2d': hlib.op.nn.conv2d,
    'nn.max_pool2d': hlib.op.nn.max_pool2d,
    'nn.avg_pool2d': hlib.op.nn.avg_pool2d,
    'nn.global_max_pool2d': hlib.op.nn.global_max_pool2d,
    'nn.global_avg_pool2d': hlib.op.nn.global_avg_pool2d,
    'nn.dropout': hlib.op.nn.dropout,
    'nn.pad' : hlib.op.nn.relay_pad,
    'transpose': hlib.op.nn.transpose,
    'reshape' : hlib.op.nn.reshape,
    'nn.batch_flatten': hlib.op.nn.flatten,
    'nn.batch_norm': hlib.op.nn.batch_norm,
    'abs': hlib.op.op.abs,
    'negative': hlib.op.op.negative,
    'add': hlib.op.op.broadcast_add,
    'subtract': hlib.op.op.broadcast_sub,
    'multiply': hlib.op.op.broadcast_mul,
    'greater': hlib.op.op.broadcast_greater,
    'divide': hlib.op.op.broadcast_div,
    'maximum': hlib.op.op.broadcast_max,
    'concatenate':hlib.op.nn.concatenate,
    'squeeze':hlib.op.nn.squeeze,
    'split': hlib.op.nn.split,
    'full': hlib.op.math.full,
    'full_like': hlib.op.math.full_like,
    'zeros': hlib.op.math.zeros,
    'zeros_like': hlib.op.math.zeros_like,
    'ones': hlib.op.math.ones,
    'ones_like': hlib.op.math.ones_like,
}
# move to same file as previous
_attrib = {
    'nn.conv2d': [
        'strides',
        'padding',
        'dilation',
        'groups',
        'channels',
        'kernel_size',
        'data_layout',
        'kernel_layout',
        'out_layout',
        'out_dtype'],
    'nn.conv2d_transpose': [
        'channels',
        'kernel_size',
        'strides',
        'padding',
        'output_padding',
        'dilation',
        'groups',
        'data_layout',
        'kernel_layout',
        'out_layout',
        'out_dtype'],
    'nn.max_pool2d': [
        'pool_size',
        'strides',
        'padding',
        'layout'],
    'nn.global_max_pool2d': [
        'layout'],
    'nn.global_avg_pool2d': [
        'layout'],
    'nn.dropout': ['rate'],
    'nn.pad': ['pad_value','pad_width'],
    'nn.avg_pool2d': [
        'pool_size',
        'strides',
        'padding',
        'layout'],
    'transpose': ['axes'],
    'reshape': [
        'newshape'],
    'squeeze': ['axis'],
    'cast': ['dtype'],
    'nn.dense': [
        'units',
        'out_dtype'],
    'nn.softmax': ['axis'],
    'nn.bias_add': ['axis'],
    'sigmoid': [],
    'tanh': [],
    'nn.relu': [],
    'nn.batch_flatten': [],
    'nn.batch_norm': ['axis','epsilon','center','scale'],
    'nn.leaky_relu': ['alpha'],
    'abs': [],
    'negative': [],
    'greater': [],
    'add': [],
    'subtract': [],
    'multiply': [],
    'divide': [],
    'maximum': [],
    'clip':['a_min','a_max'],
    'concatenate': ['axis'],
    'squeeze': ['axis'],
    'split': [
        'indices_or_sections',
        'axis'],
    'full': ['shape', 'dtype'],
    'full_like': [],
    'zeros': ['shape', 'dtype'],
    'zeros_like': [],
    'ones_like': [],
    'exp': [],
    'log': []
}


#change to get_model
def get_model(model, shape):
    """Gets the module (computation graph) and the parameters from the Keras model

    Parameters
    ----------
    model : str
        Path to model generated by Keras

    shape : dict
        Dictionary of input shapes into the model

    Returns
    -------
    module : tvm.relay.Module
        A relay module that contains the contents of the net

    params : dict of str to NDArray
        Parameters needed for the model
    """
    relay_model = keras.models.load_model(model)
    module, params = relay_front.from_keras(relay_model, shape)
    return module, params

#move to util. Change to tvm_to_primitive
def tvm_to_primitive(expr):
    if not isinstance(expr,int):
        return expr.value
    else:
        return expr

#move to util
def update_if(cur_dict, ap_dict):
    """Adds item to the dict if key is not already in dict

    Parameters
    ----------
    cur_dict : dict
        The dictionary we wish to update

    ap_dict : dict
        The dictionary we want to append to the current dictionary
        without overwriting any current keys

    Returns
    -------
    cur_dict : dict
        The dictionary that has been updated
    """
    assert type(cur_dict) == type(ap_dict) == dict
    "type must be a dict"
    for key in ap_dict:
        if key not in cur_dict:
            cur_dict[key] = ap_dict[key]
    return cur_dict

#move to util
def partial_flatten(l):
    """Flattens first layer of lists
    i.e.: [1,[2],[[3]]] -> [1,2,[3]]

    Parameters
    ----------
    l : list
        the list we wish to partially flatten

    Returns
    -------
    _list : list
        the list that has been partially flattened

    """
    _list = []
    for sublist in l:
        if isinstance(sublist, list):
            for item in sublist:
                _list.append(item)
        else:
            _list.append(sublist)
    return _list

#move to util
def full_flatten(l):
    """Fully flattens the list (excluding str and bytes)
    i.e.: [1,[2],[[3]]] -> [1,2,3]

    Parameters
    ----------
    l : list
        the list we wish to fully flatten

    Returns
    -------
    _ : list
        the list that was fully flattened
    """
    def _flatten(l):
        for x in l:
            if isinstance(
                    x, (list, tuple)) and not isinstance(
                    x, (str, bytes)):
                for item in _flatten(x):
                    yield item
            else:
                yield x
    return list(_flatten(l))

#move to util
def fst(l):
    """Returns the first item in any list

    Parameters
    ---------
    l : list
        the list we want to extract the first item from

    Returns
    -------
        first item in list
    """
    if isinstance(l, list):
        return fst(l[0])
    else:
        return l


def gen_params(type_dict, env):
    """Finds the parameters that we need to extract from the model

    Parameters
    ---------
    type_dict: dict
        the dictionary that contains the type of each variable in the environment

    env: dict
        the dictionary that contains the computational environment that sets up the
        contained function {key: value:}

    Returns
    -------
        a list of hcl.tensor.Tensor placeholders to hold the model params
    """

    params = []
    for var in type_dict:
        if (type_dict[var] == Var):
            params.append(env[var])
        elif (type_dict[var] == Tuple):
            for item in env[var]:
                if isinstance(item, hcl.tensor.Tensor):
                    update_if(env, {item.name : item})
    return params

#move to util
def isPureList(item):
    """determines if a list is a list and not a sequence of chars or bytes

    Parameters
    ---------
    item: list
        object the user is trying to determine is a pure list

    Returns
    -------
        if the list meets the criteria stated above
    """
    return isinstance(item, list) and not isinstance(item, (str, bytes))

#tuple_extract
def tup_dev(tup, dict_t, env):
    """takes a tuple and returns all the objects inside of it in a flat list

    Parameters
    ---------
    tup: tuple
        the tuple of objects we're trying to infer from
    
    type_dict: dict
        a dictionary of each object's type

    env: dict
        a dictionary of each object's computing environment

    Returns
    -------
        a list of objects
    """
    result = []
    if isPureList(tup):
        for item in tup:
            result.append(tup_dev(item, dict_t, env))
    else:
        tp = dict_t[tup]
        if tp == Var:
            result.append(env[tup])
        if tp == Tuple:
            tup_env = env[tup]
            result.append(tup_dev(tup_env[1], tup_env[2], tup_env[3]))
    return tuple(result)

#let_bind (can be used for other frontends like Tensorflow, PyTorch)
def bind(ntype, *arg):
    """binds a computation to a variable

    Parameters
    ---------
    ntype: tvm.relay-expr
        the type of the binding

    *arg: list of arguments
        the arguments required for each ntype

    Returns
    -------
        the object we bind to the output
    """
    print("In bind")
    if ntype == Call:
        var = arg[0]
        call_var = var[-1]
        type_dict = arg[1]
        call_type = type_dict[call_var]
        bind_env = arg[2]
        params = arg[3]

        if(call_type == Function):
            call_args = bind_env[var[-2]]
            call_env = bind_env[call_var]
            call_env = (call_env[2])[call_var]
            _var = call_env[0]
            _dict = call_env[1]
            _env = call_env[2]
            _size = call_env[3]
            new_params = []
            for arg in _var:
                if arg in params:
                    new_params.append(arg)
            _func = gen_func(new_params, _var, _dict, _env, _size)
            return _func(*call_args)
        elif(call_type == Call):
            _func = bind_env[call_var][1]
            _args = bind_env[call_var][2]
            _kwargs = bind_env[call_var][3]
            _args = list(_args)
            for i in range(len(_args)):
                item = _args[i]
                if isinstance(item, str):
                    if type_dict[item] == Call:
                        inner_func = bind_env[item][1]
                        inner_args = bind_env[item][2]
                        inner_kwargs = bind_env[item][3]
                        _args[i] = inner_func(*inner_args, **inner_kwargs)
            _args = tuple(_args)
            arg_list = []
            for _var in _args:
                if _var in params:
                    arg_list.append(_var)
                else:
                    arg_list.append(_var)
            return _func(*arg_list, **_kwargs)
    if ntype == Tuple:
        var = arg[0][0]
        env = arg[2]
        tup = env[var][1]
        dict_type = env[var][2]
        tup_env = env[var][3]
        return tup_dev(tup, dict_type, tup_env)
    if ntype == Var:
        name = arg[0][0]
        return (arg[2])[name]
    else:
        print("Type not implemented yet")

#group helper functions in one section
def isInParams(var,params):
    if(not isinstance(var, hcl.tensor.Tensor)):
        return False
    
    for par in params:
        isShape = (var.shape==par.shape)
        isName  = (var.name==par.name)
        isType  = (var.dtype==par.dtype)
        if(isShape and isName and isType):
            return True
    return False

#move to utils, tup->tpl
def gen_tup(var, env):
    def change_list(var, env):
        l=[]
        for inx in range(len(var)):
            if(not isPureList(var[inx])):
                l.append(env[var[inx]])
            else:
                l.append(change_list(var[inx],env))
        return tuple(l)
    return change_list(var,env)

#think of another name (work on spacing)
def resolve_env(item,params,var,type_dict,env,size):
    print("Item:",item)
    if(type_dict[item] == Function):
        print("In Func")
        _var = env[0]
        _type_dict = env[1]
        _env = env[2]
        _params = gen_params(type_dict, env)
        _size = env[3]
        f = gen_func(_params, _var, _type_dict, _env, _size)
        env[item] = f
        type_dict[item] = Call
    elif(type_dict[item] == Let):
        print("In Let")
        _ntype = env[item][0]
        _bind_var = env[item][1]
        _var = env[item][2]
        _dict = env[item][3]
        _env = env[item][4]
        _bind_var = bind(_ntype, _var, _dict, _env, params)
        env[item] = _bind_var
        type_dict[item] = Var
    elif(type_dict[item] == Call):
        print("In Call")
        if(not isinstance(env[item],hcl.tensor.Tensor)):
            #print(env)
            #print(env[item])
            name = env[item][0]
            _func = env[item][1]
            _args = env[item][2]
            _kwargs = env[item][3]
            arg_list = []
            for _var in _args:
                if isInParams(_var,params):
                    arg_list.append(_var)
                else:
                    if(isinstance(_var,tuple)):
                        for v in _var:
                            arg_list.append(v)
                    elif isinstance(_var,str):
                        if(isinstance(env[_var],tuple)):
                            var,env[_var] = resolve_env(_var,params,var,type_dict,env,size)
                            if(type_dict[_var]==Tuple):
                                arg_list = env[_var]
                        else:
                            arg_list.append(env[_var])
                    else:
                        arg_list.append(_var)
            #print(arg_list)
            if(len(arg_list) != 0):
                env[item] = _func(*arg_list, **_kwargs)
                #print(type(env[item]))
            else:
                env[item] = _func(**_kwargs)
            type_dict[item] = Var
        else:
            var,env[_var] = resolve_env(_var,params,var,type_dict,env,size)
    elif(type_dict[item]==Tuple):
        if(not isinstance(env[item][0],hcl.tensor.Tensor)):
            #print(env[item])
            name = env[item][0]
            tup_res = env[item][1]
            tup_dict = env[item][2]
            tup_env = env[item][3]
            tup = []
            for _var in tup_res:
                tup.append(env[_var])
            env[item] = tuple(tup)
        else:
            var.insert(0,item)
            env[item] = env[item]
    elif(type_dict[item] == TupleGetItem):
        tup_name = env[item][2]
        index = env[item][3]
        tup = env[tup_name]
        env[item] = tup[index]
        type_dict[item] = Var
    #print(var,item)
    var.remove(item)
    return var,env[item]

#remove size
def gen_func(params, var, type_dict, env, size):
    args = []
    for _var in params:
        args.append(_var)
    def func(*args):
        print("In func")
        _var = var
        while(len(_var)!=0):
            item = _var[0]
            _var,env[item]=resolve_env(item,args,_var,type_dict,env,size)
        return env[item]
    return func

#think of better name (build_node_map)
def model_extent(func, main=False, node_map=None,cur_length=[0]):
    length = 0
    if isinstance(func, Call):
        if(node_map!=None):
            for node in node_map:
                if(tvm.relay.analysis.alpha_equal(node,func)):
                    return 0
        for arg in func.args:
            if(isinstance(arg, Call)):
                length += model_extent(arg, main,node_map,cur_length)
            elif(isinstance(arg, TupleGetItem)):
                length += model_extent(arg, main,node_map,cur_length)
            elif(isinstance(arg, Tuple)):
                length += model_extent(arg, main,node_map,cur_length)
        if(isinstance(func.op, Function)):
            length += model_extent(func.op, main,node_map,cur_length)
        if(node_map!=None): 
            node_map = update_if(node_map,{func:[cur_length[0],0]})
            cur_length[0]+=1
        length += 1
        return length
    elif isinstance(func, Let):
        length += model_extent(func.value, main)
        length += model_extent(func.body, main)
        return length
    elif isinstance(func, Function):
        length += model_extent(func.body, main)
        return length
    elif isinstance(func, Tuple):
        length=1
        if(node_map!=None):
            if(func in node_map):
                return 0
        for field in func.fields:
            length += model_extent(field, main, node_map, cur_length)
        if(node_map!=None):
            node_map = update_if(node_map,{func:[cur_length[0],0]})
            cur_length[0]+=1
        return length
    elif isinstance(func, TupleGetItem):
        length = 1
        if(node_map != None):
            if(func in node_map):
                return 0
        length += model_extent(func.tuple_value, main,node_map,cur_length)
        if(node_map != None):
            node_map = update_if(node_map,{func:[cur_length[0],0]})
            cur_length[0]+=1
        return length
    else:
        return 0

#get rid of this
def gen_schedule(args, func):
    return hcl.create_schedule(args, func)

def gen_args(node):
    pass


def relay_parser(model, shape, frontend='keras', dtype=hcl.Float()):
    hcl.init(dtype)
    input_defined = {} #defined_inputs
    node_map = {}
    global_vars = []
    for item in shape:
        input_defined[item] = None
    if frontend == 'keras':
        try:
            keras_model = keras.models.load_model(model)
        except:
            keras_model = model
        module, params = relay_front.from_keras(keras_model, shape)
        print(module)
        body = module.functions[module.global_var_map_["main"]]
        place_num = model_extent(body.body,True,node_map,[0])

    #move these outside
    #get_type
    def getType(ty, name):
        if isinstance(ty, TensorType):
            dtype = ty.dtype
            size = []
            for i in ty.shape:
                size.append(i.value)
            return hcl.placeholder(tuple(size), name, dtype)
        elif isinstance(ty, TupleType):
            t_vars = []
            for i in range(len(ty.fields)):
                var_name = name + "_" + str(i)
                t_vars.append(getType(ty.fields[i], var_name))
            return tuple(t_vars)
        else:
            pass

    #get_Item
    def getItem(env):
        #print("getItem",env)
        tup_type = env[1]
        if tup_type == Var:
            tup = list(env[2])
            index = env[3]
            item = tup[index]
            if(isinstance(item, tuple)):
                name = env[0]
            else:
                name = item.name
            inst_type = {name: Var}
            inst_env = {name: item}
        if tup_type == Call:
            name = env[0]
            tup = env[2]
            index = env[3]
        return item, name, inst_type, inst_env, inst_var

    #change name to id, remove place
    def gen_call(node,name,opname,place):
        #print(name)
        args = []
        var = []
        type_dict = {name: Call}
        env = {}
        arg_len = 0
        temp_len = 0
        partial_extent = 0
        for arg in node.args:
            temp_var, temp_type, temp_env, size = parse_rec(arg, place - partial_extent - 1)
            partial_extent = partial_extent + size
            if isinstance(arg, Var):
                var.append(temp_var[0])
                var = partial_flatten(var)
                args.append(temp_env[fst(temp_var[0])])
            elif isinstance(arg, Constant):
                var.append(temp_var)
                var = partial_flatten(var)
                args.append(temp_env[temp_var[0]])
                temp_len += len(temp_env)
                env.update(temp_env)
            elif isinstance(arg, Call):
                var.append(temp_var)
                var = partial_flatten(var)
                args.append(temp_env[temp_var[-1]][0])
                temp_len += len(temp_env)
                env.update(temp_env)
            elif isinstance(arg, TupleGetItem):
                if(temp_env[temp_var[-1]][1]==Var):
                    item, item_name, temp_type, temp_env, inst_var = getItem(
                        temp_env[temp_var[-1]])
                    var.append(inst_var)
                    var = partial_flatten(var)
                    args.append(item)
                    env.update(temp_env)
                else:
                    #print("hi",temp_env[temp_var[-1]])
                    args.append(temp_env[temp_var[-1]][0])
                    var.append(temp_var)
                    var = partial_flatten(var)
                    env.update(temp_env)
                    #var = temp_var
                    #env = temp_env
            elif isinstance(arg, Tuple):
                tup_var = temp_var[-1]
                temp_var = partial_flatten(temp_var)
                #print("temp_var:",temp_var)
                var.append(temp_var)
                var = partial_flatten(var)
                tup_env={}
                #print("temp_env:",temp_env[tup_var][3])
                t_name = temp_env[tup_var][0]
                t_res = temp_env[tup_var][1]
                t_dict = temp_env[tup_var][2]
                t_env = temp_env[tup_var][3]
                tup_env[tup_var]=(t_name,t_res,t_dict,t_env)
                args.append(tup_var)
                env.update(tup_env)
                update_if(env,t_env)
            type_dict.update(temp_type)
        arg_len = len(var) - temp_len
        var.append(name)
        kwargs = {}
        for i in range(len(args)):
            if hasattr(args[i], "name"):
                if(args[i].name in var):
                    env[args[i].name] = args[i]
        if opname in _attrib:
            for attr in _attrib[opname]:
                kwargs[attr] = getattr(node.attrs, attr)
            env[name] = (name, _convert_map[opname], tuple(args), kwargs)
        else:
            env[name] = (name, tuple(args))
        if isinstance(node.op, Function):
            temp_var, temp_type, temp_env, _ = parse_rec(node.op, place - 1)
            var.append(opname)
            type_dict.update({opname: Function})
            env[opname] = (temp_var, temp_type, temp_env)
        #print("CALL VAR:" var)
        return var, type_dict, env

    #change g_env to global_env
    def parse_rec(node, place, init=False, g_env={}):
        #checks if the node has been parsed before
        if(isinstance(node,(Call,Tuple))):
            if(node_map[node][1]>0):
                name = "%" + str(node_map[node][0])
                var = [name]
                type_dict = {}
                env={}
                env[name]=g_env[name]
                return var,type_dict,env,0
            else:
                node_map[node][1]+=1

        if isinstance(node, Function):
            name = "%" + str(len(node_map))
            print("Function: ", name)
            var = [name]
            type_dict = {name: Function}
            env = {}
            temp_var, temp_type, temp_env, _ = parse_rec(node.body, place - 1,g_env)
            if init:
                var = temp_var
                type_dict = temp_type
                env = temp_env
            else:
                env = update_if(
                    env, {
                        name: (
                            full_flatten(temp_var), temp_type, temp_env, len(node_map))})
        elif isinstance(node, Var):
            name = node.name_hint
            var = [name]
            type_dict = {name: Var}
            ty = node.type_annotation
            env = {}
            if node.name_hint in shape:
                dtype = ty.dtype
                if input_defined[name]==None:
                    env[name] = hcl.placeholder(shape[name], name, dtype)
                    input_defined[name]=env[name]
                else:
                    env[name]=input_defined[name]
            else:
                env[name] = getType(ty, name)
            print("Var: " + name)
        elif isinstance(node, Constant):
            name = "con("+str(node.data)+")"
            print("Constant: " + name)
            var = [name]
            type_dict = {name: Constant}
            data = node.data
            env={}
            constant = hcl.asarray(data.asnumpy())
            env[name] = hcl.local(float(node.data.asnumpy()))
            """if not name in input_defined:
                input_defined[name]=array
            env[name] = array"""
        elif isinstance(node, TupleGetItem):
            index = node.index
            tup = node.tuple_value
            if isinstance(tup, Var):
                var_name = tup.vid.name_hint
                name = "get_" + var_name + "_" + str(index)
                ty = tup.type_annotation
                var = [name]
                type_dict = {name: TupleGetItem}
                env = {}
                env[name] = (name, Var, getType(ty, var_name), index)
            elif isinstance(tup, Call):
                name = '%' + str(node_map[tup][0])
                get_name = 'get' + str(node_map[tup][0]) + "_" + str(index)
                if(not hasattr(tup.op, "name")):
                    opname = '%' + str(node_map[tup][0] - 1)
                else:
                    opname = tup.op.name
                var, type_dict,env = gen_call(tup,name,opname,node_map[tup][0])
                var.append(get_name)
                type_dict.update({get_name: TupleGetItem})
                env[get_name] = (get_name, TupleGetItem, name, index)
            print("TupleGet: " + get_name)
        elif isinstance(node, Let):
            name = node.var.vid.name_hint
            print("Let: " + name)
            var = [name]
            type_dict = {name: Let}
            env = {}
            args = []
            kwargs = {}
            ty = node.var.type_annotation
            arg_len = 0
            temp_len = 0
            bind_var = getType(ty, name)
            value = node.value
            val_len = node_map[value][0]
            temp_var, temp_type, temp_env, _ = parse_rec(value, place)
            if isinstance(value, Var):
                env = update_if(env, {name: (Var, bind_var, temp_type,
                                             temp_env[fst(temp_var[0])])})
            elif isinstance(value, Function):
                env = update_if(
                    env, {
                        name: (
                            Function, bind_var, temp_var, temp_type, temp_env)})
            elif isinstance(value, Tuple):
                env = update_if(
                    env, {
                        name: (
                            Tuple, bind_var, temp_var, temp_type, temp_env)})
            elif isinstance(value, TupleGetItem):
                item, get_name, get_type, get_env, _ = getItem(
                    temp_env[temp_var[0]])
                temp_var = [get_name]
                temp_type = {get_name: get_type}
                temp_env = {get_name: item}
                env = update_if(
                    env, {
                        name: (
                            get_type[get_name], bind_var, temp_var, temp_type, temp_env)})
            elif isinstance(value, Call):
                if not hasattr(value.op, "name"):
                    opname = "%" + str(node_map[tup][0])
                else:
                    opname = value.op.name
                args = temp_env[temp_var[-1]][0]
                env = update_if(env, temp_env)
                temp_len += len(temp_env)
                arg_len = len(temp_var) - temp_len
                for i in range(len(args)):
                    if hasattr(args[i], "name"):
                        if(args[i].name in temp_var):
                            env[args[i].name] = args[i]
                if opname in _attrib:
                    for attr in _attrib[opname]:
                        kwargs[attr] = getattr(value.attrs, attr)
                env[name] = (Call,
                             bind_var,
                             temp_var,
                             temp_type,
                             temp_env)
            type_dict = update_if(type_dict, temp_type)
            temp_var, temp_type, temp_env, _ = parse_rec(
                node.body, place - (val_len))
            var.append(temp_var)
            type_dict = update_if(type_dict, temp_type)
            env = update_if(env, temp_env)
        elif isinstance(node, If):
            print("If not instantiated yet")
        elif isinstance(node, Tuple):
            tup_inx = node_map[node][0]
            name = "%" + str(node_map[node][0])
            print("Tuple: " + name)
            var = []
            type_dict = {name: Tuple}
            env = {}
            tup_type_dict = {}
            tup_res = []
            tup = []
            tup_env = {}
            inx = 0
            partial_extent = 1
            for field in node.fields:
                if isinstance(field, Tuple):
                    inx = inx + 1
                temp_var, temp_type, temp_env, size = parse_rec(
                    field, tup_inx - partial_extent - 1)
                partial_extent = partial_extent+size
                tup.append(temp_var)
                tup_res.append(temp_var[-1])
                tup_type_dict.update(temp_type)
                tup_env.update(temp_env)
            var.append(tup)
            var.append([name])
            var = partial_flatten(var)
            update_if(type_dict,tup_type_dict)
            env.update(tup_env)
            env[name] = (name, tup_res, tup_type_dict, tup_env)
        elif isinstance(node, Call):
            if(not hasattr(node.op, "name")):
                opname = '%' + str(node_map[node][0])
            else:
                opname = node.op.name
            name = '%' + str(node_map[node][0])
            print("Call " + name + ":" + opname)
            var, type_dict, env = gen_call(node,name,opname,place)
        if(not isinstance(node,Function)):
            g_env[name]=env[name]
        #print("CURRENT VAR:", var)
        return var, type_dict, env, 0
    out_var, out_type, out_env, _ = parse_rec(body, place_num, True)
    #print("out_var:",out_var)
    return out_var, out_type, out_env, place_num, params

#only used by user. Add comment
def get_relay_model(
        model,
        shape={},
        frontend='keras',
        dtype=hcl.Float(),
        in_params=None):
    out_var, out_type, out_env, place_num, params = relay_parser(
        model, shape, frontend)
    out_var = full_flatten(out_var)
    _param = gen_params(out_type, out_env)
    #_param.sort(key=lambda x: x.name)
    v_param = [holder for holder in _param if ("_param" in holder.name)]
    v_input = [holder for holder in _param if ("input" in holder.name)]
    v_param.sort(key=lambda x: int(''.join(filter(lambda i: i.isdigit(), x.name))))
    v_input.sort(key=lambda x: int(''.join(filter(lambda i: i.isdigit(), x.name))))
    _param = partial_flatten([v_input,v_param])
    func = gen_func(_param, out_var, out_type, out_env, place_num)
    _inputs = []
    if(params is None):
        params = in_params
    for var in params:
        _inputs.append(hcl.asarray(params[var].asnumpy()))
    s = gen_schedule(_param, func)
    print(hcl.lower(s))
    print(_param)
    return hcl.build(s), _inputs
