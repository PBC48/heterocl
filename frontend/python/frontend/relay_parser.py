import tvm
import keras
import tvm.relay.frontend as relay_front
import numpy as np
import heterocl as hcl
import hlib
#from copy import deepcopy
from tvm.relay.expr import Function, Var, Call, Let, If, Constant
from tvm.relay.expr import TupleGetItem, Tuple
from tvm.relay.ty import TensorType, TupleType

# Exploring the AST here
hcl.init(hcl.Float())
_convert_map = {
    'nn.dense': hlib.nn.dense,
    'nn.relu': hlib.nn.relu,
    'nn.bias_add': hlib.nn.bias_add,
    #    'prelu'                   : 'hlib.nn.prelu',
    'tanh': hlib.math.tanh,
    'sigmoid': hlib.math.sigmoid,
    'nn.softmax': hlib.nn.softmax,
    'exp': hlib.math.exp,
    'log': hlib.math.log,
    'sqrt': hlib.math.sqrt,
    'nn.conv2d': hlib.nn.conv2d,
    'nn.max_pool2d': hlib.nn.max_pool2d,
    'nn.avg_pool2d': hlib.nn.avg_pool2d,
    'nn.dropout': hlib.nn.dropout,
    'nn.pad' : hlib.nn.relay_pad,
    'transpose': hlib.nn.transpose,
    'reshape' : hlib.nn.reshape,
    'nn.batch_flatten': hlib.nn.flatten,
    'add': hlib.broadcast_add,
    'subtract': hlib.broadcast_sub,
    'multiply': hlib.broadcast_mul,
    'divide': hlib.broadcast_div,
    'maximum': hlib.broadcast_max,
    'concatenate':hlib.nn.concatenate,
    'split': hlib.nn.split,
    'full': hlib.math.full,
    'full_like': hlib.math.full_like,
    'zeros': hlib.math.zeros,
    'zeros_like': hlib.math.zeros_like,
    'ones': hlib.math.ones,
    'ones_like': hlib.math.ones_like,
}

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
    'nn.dense': [
        'units',
        'out_dtype'],
    'nn.softmax': ['axis'],
    'nn.bias_add': ['axis'],
    'sigmoid': [],
    'tanh': [],
    'nn.relu': [],
    'nn.batch_flatten': [],
    'add': [],
    'subtract': [],
    'multiply': [],
    'divide': [],
    'maximum': [],
    'concatenate': ['axis'],
    'split': [
        'indices_or_sections',
        'axis'],
    'full': ['shape', 'dtype'],
    'full_like': [],
    'zeros': ['shape', 'dtype'],
    'zeros_like': [],
    'ones_like': [],
}


def get_mod(model, shape):
    """gets the module and the parameters from the Keras model

    Parameters
    ----------
    model : str
        path to model generated by Keras

    shape : dict
        dictionary of input shapes into the model

    Returns
    -------
    module : tvm.relay.Module
        A relay module that contains the contents of the net

    params : dict of str to NDArray
        parameters needed for the model
    """
    relay_model = keras.models.load_model(model)
    module, params = frontend.from_keras(relay_model, shape)
    return module, params


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
    print("Env:",env)
    print("Type Dict:",type_dict)
    params = []
    for var in type_dict:
        if (type_dict[var] == Var):
            params.append(env[var])
        elif (type_dict[var] == Tuple):
            print(env[var])
            for item in env[var]:
                if isinstance(item,hcl.tensor.Tensor):
                    update_if(env,{item.name : item})
    return params

def isPureList(item):
    return isinstance(item, list) and not isinstance(item, (str, bytes))

def tup_dev(tup, dict_t, env):
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


def bind(ntype, *arg):
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

def isInParams(var,params):
    if(not isinstance(var,hcl.tensor.Tensor)):
        return False
    
    for par in params:
        isShape = (var.shape==par.shape)
        isName  = (var.name==par.name)
        isType  = (var.dtype==par.dtype)
        if(isShape and isName and isType):
            return True
    return False

def getItem(env):
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
        tup = env[2]
        index = env[3]
        args = env[4]
        print(tup)
        print(args[0])
        if(isinstance(tup)):
            pass
    return item, name, inst_type, inst_env

def gen_tup(var,env):
    def change_list(var,env):
        l=[]
        for inx in range(len(var)):
            if(not isPureList(var[inx])):
                l.append(env[var[inx]])
            else:
                l.append(change_list(var[inx],env))
        return tuple(l)
    return change_list(var,env)


def resolve_env(item,params,var,type_dict,env,size):
    print("Env:",env)
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
    if(type_dict[item] == Let):
        print("In Func")
        _ntype = env[item][0]
        _bind_var = env[item][1]
        _var = env[item][2]
        _dict = env[item][3]
        _env = env[item][4]
        _bind_var = bind(_ntype, _var, _dict, _env, params)
        env[item] = _bind_var
        type_dict[item] = Var
    if(type_dict[item] == Call):
        print("In Call")
        print(env[item])
        if(not isinstance(env[item],hcl.tensor.Tensor)):
            name = env[item][0]
            _func = env[item][1]
            _args = env[item][2]
            print("Arg:",_args)
            _kwargs = env[item][3]
            arg_list = []
            print('hi',_args)
            for _var in _args:
                print("Var:",_var)
                if isInParams(_var,params):
                    arg_list.append(_var)
                else:
                    if(isinstance(_var,tuple)):
                        for v in _var:
                            arg_list.append(v)
                    elif isinstance(_var,str):
                        if(isinstance(env[_var],tuple)):
                            var,env[_var] = resolve_env(_var,params,var,type_dict,env,size)
                        else:
                            arg_list.append(env[_var])
                    else:
                        arg_list.append(_var)
            if(len(arg_list) != 0):
                env[item] = _func(*arg_list, **_kwargs)
            else:
                env[item] = _func(**_kwargs)
        else:
            var,env[_var] = resolve_env(_var,params,var,type_dict,env,size)
        print("Params:",params)
    if(type_dict[item]==Tuple):
        print(item)
        print(env[item])
        name = env[item][0]
        tup_res = env[item][1]
        tup_dict = env[item][2]
        tup_env = env[item][3]
        tup = []
        for _var in tup_res:
            tup.append(env[_var])
        env[item] = tuple(tup)
    var.remove(item)
    return var,env[item]

def gen_func(params, var, type_dict, env, size):
    args = []
    print("Par:",params)
    for _var in params:
        args.append(_var)
    def func(*args):
        print("In func")
        _var = var
        print(_var)
        while(len(_var)!=0):
            item = _var[0]
            _var,env[item]=resolve_env(item,args,_var,type_dict,env,size)
            print(len(_var))
            print(type_dict[item])
            print("ENV:",env[item])
        return env[item]
    return func


def model_extent(func, main=False):
    length = 0
    if isinstance(func, Call):
        length = 1
        for arg in func.args:
            if(isinstance(arg, Call)):
                length += model_extent(arg, main)
            elif(isinstance(arg, TupleGetItem)):
                length += model_extent(arg, main)
            elif(isinstance(arg, Tuple)):
                length += model_extent(arg, main)
        if(isinstance(func.op, Function)):
            length += model_extent(func.op, main)
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
        for field in func.fields:
            length += model_extent(field,main)
        return length
    elif isinstance(func, TupleGetItem):
        length += model_extent(func.tuple_value, main)
        return length
    else:
        return 0


def gen_schedule(args, func):
    return hcl.create_schedule(args, func)

# creating relay_to_hcl parser


def relay_parser(model, shape, frontend='keras', dtype=hcl.Float()):
    hcl.init(dtype)
    input_defined = {}
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
        place_num = model_extent(body.body, True)
    elif frontend == 'relay':
        body = model
        place_num = model_extent(body, True)
        params = None

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

    def parse_rec(node, place, init=False):
        node_extent = model_extent(node)
        if isinstance(node, Function):
            name = "%" + str(place)
            print("Function: ", name)
            var = [name]
            type_dict = {name: Function}
            env = {}
            temp_var, temp_type, temp_env, _ = parse_rec(node.body, place - 1)
            if(init):
                var = temp_var
                type_dict = temp_type
                env = temp_env
            else:
                env = update_if(
                    env, {
                        name: (
                            full_flatten(temp_var), temp_type, temp_env, node_extent)})
        elif isinstance(node, Var):
            name = node.name_hint
            var = [name]
            type_dict = {name: Var}
            ty = node.type_annotation
            env = {}
            if node.name_hint in shape:
                dtype = ty.dtype
                if input_defined[name]==None:
                    print("In here:",name)
                    env[name] = hcl.placeholder(shape[name], name, dtype)
                    input_defined[name]=env[name]
                else:
                    env[name]=input_defined[name]
            else:
                env[name] = getType(ty, name)
            print("Var: " + name)
        elif isinstance(node, Constant):
            name = "con"+str(node.data)
            print("Constant: "+name)
            var = [name]
            type_dict = {name: Constant}
            data = node.data
            env={}
            constant = hcl.asarray(data.asnumpy())
            print(type(constant))
            array = hcl.placeholder(constant.shape,constant.dtype)
            array = constant
            env[name] = array
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
                opname = '%' + str(place - 1)
                name = "get_" + opname
                args = tup.args
                var = [name]
                type_dict = {name: TupleGetItem}
                env = {}
                env[name] = (name, Call, opname, index, args)
            print("TupleGet: " + name)
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
            val_len = model_extent(value)
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
                    opname = "%" + str(place - 1)
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
            tup_inx = model_extent(node)
            name = "%" + str(place)
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
                print(temp_var)
                tup.append(temp_var)
                tup_res.append(temp_var[-1])
                tup_type_dict.update(temp_type)
                tup_env.update(temp_env)
            var.append(tup)
            var.append([name])
            var = partial_flatten(var)
            update_if(type_dict,tup_type_dict)
            update_if(env,tup_env)
            env[name] = (name, tup_res, tup_type_dict, tup_env)
        elif isinstance(node, Call):
            if(not hasattr(node.op, "name")):
                opname = '%' + str(place - 1)
            else:
                opname = node.op.name
            print("Call: " + opname)
            name = '%' + str(place)
            args = []
            var = []
            type_dict = {name: Call}
            env = {}
            arg_len = 0
            temp_len = 0
            partial_extent = 0
            inx = 0
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
                    item, item_name, temp_type, temp_env = getItem(
                        temp_env[temp_var[0]])
                    var.append(item_name)
                    var = partial_flatten(var)
                    args.append(item)
                    env.update(temp_env)
                elif isinstance(arg, Tuple):
                    tup_var = temp_var[-1]
                    temp_var = partial_flatten(temp_var)
                    print(temp_var)
                    var.append(temp_var)
                    var = partial_flatten(var)
                    tup_env={}
                    print(temp_env[tup_var])
                    t_name = temp_env[tup_var][0]
                    t_res = temp_env[tup_var][1]
                    t_dict = temp_env[tup_var][2]
                    t_env = temp_env[tup_var][3]
                    tup_env[tup_var]=(t_name,t_res,t_dict,t_env)
                    print(tup_env[tup_var])
                    res = gen_tup(temp_env[tup_var][1],temp_env[tup_var][3])
                    print(res)
                    ##print(temp_env[tup_var][1],temp_env[tup_var][3])
                    print("Tup:",tup_env)
                    for v in res:
                        args.append(v)
                    #print(temp_env[tup_var][1],temp_env[tup_var][3])
                    #tup_env[tup_var]=gen_tup(temp_env[tup_var][1],temp_env[tup_var][3])
                    #print(args)
                    env.update(tup_env)
                type_dict.update(temp_type)
                inx = inx + 1
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
        print("ENDING VAR:",var)
        return var, type_dict, env, node_extent
    out_var, out_type, out_env, _ = parse_rec(body, place_num, True)
    return out_var, out_type, out_env, place_num, params


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
    func = gen_func(_param, out_var, out_type, out_env, place_num)
    _inputs = []
    if(params is None):
        params = in_params
    for var in params:
        _inputs.append(hcl.asarray(params[var].asnumpy()))
    s = gen_schedule(_param, func)
    print(hcl.lower(s))
    print("Schedule built")
    return hcl.build(s), _inputs
