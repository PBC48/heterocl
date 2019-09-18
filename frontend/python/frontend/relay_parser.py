import tvm
import keras
import tvm.relay.frontend as relay_front
import numpy as np
import heterocl as hcl
import hlib
from tvm.relay.expr import Function, Var, Call, Let, If, TupleGetItem, Tuple
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
    'transpose': hlib.nn.transpose,
    'nn.batch_flatten': hlib.nn.flatten,
    'add': hlib.broadcast_add,
    'sub': hlib.broadcast_sub,
    'multiply': hlib.broadcast_mul,
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
    'nn.avg_pool2d': [
        'pool_size',
        'strides',
        'padding',
        'layout'],
    'transpose': ['axes'],
    'reshape': [
        'newshape',
        'reverse'],
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
    'sub': [],
    'multiply': [],
    'split': [
        'indices_or_sections',
        'axis'],
    'full': ['shape', 'dtype'],
    'full_like': [],
    'zeros': ['shape', 'dtype'],
    'zeros_like': [],
    'ones': ['shape', 'dtype'],
    'ones_like': [],
}


def get_mod(model, shape):
    relay_model = keras.models.load_model(model)
    module, params = frontend.from_keras(relay_model, shape)
    return module, params


def update_if(cur_dict, ap_dict):
    assert type(cur_dict) == type(ap_dict) == dict
    "type must be a dict"
    for key in ap_dict:
        if key not in cur_dict:
            cur_dict[key] = ap_dict[key]
    return cur_dict


def partial_flatten(l):
    _list = []
    for sublist in l:
        if isinstance(sublist, list):
            for item in sublist:
                _list.append(item)
        else:
            _list.append(sublist)
    return _list


def full_flatten(l):
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
    if isinstance(l, list):
        return fst(l[0])
    else:
        return l


def gen_params(type_dict, env):
    params = []
    for var in type_dict:
        if (type_dict[var] == Var):
            params.append(env[var])
    return params


def tup_dev(tup, dict_t, env):
    result = []
    if isinstance(tup, list) and not isinstance(tup, (str, bytes)):
        for item in tup:
            result.append(tup_dev(item, dict_t, env))
    else:
        tp = dict_t[tup]
        if tp == Var:
            result.append(env[tup])
    return tuple(result)


def bind(ntype, *arg):
    if ntype == Call:
        var = arg[0]
        print("Var Space:",var)
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
            print(_func,_args,_kwargs,type_dict)
            for i in range(len(_args)):
                item = _args[i]
                if isinstance(item,str):
                    print(item,type_dict[item])
                    if type_dict[item]==Call:
                        inner_func = bind_env[item][1]
                        inner_args = bind_env[item][2]
                        inner_kwargs = bind_env[item][3]
                        print(inner_func,inner_args,inner_kwargs)
                        _args[i] = inner_func(*inner_args,**inner_kwargs)
                    if type_dict[item]==TupleGetItem:
                        print("TupleGet")
            _args = tuple(_args)
            print(_args)
            arg_list = []
            for _var in _args:
                if _var in params:
                    arg_list.append(_var)
                else:
                    arg_list.append(_var)
            return _func(*arg_list, **_kwargs)
    if ntype == Tuple:
        print(arg)
        var = arg[0][0]
        env = arg[2]
        tup = env[var][1]
        dict_type = env[var][2]
        tup_env = env[var][3]
        return tup_dev(tup, dict_type, tup_env)
    else:
        print("Type not implemented yet")


def gen_func(params, var, type_dict, env, size):
    args = []
    for _var in params:
        args.append(_var)

    def func(*args):
        print(env)
        print(var)
        print(type_dict)
        for item in var:
            if(type_dict[item] == Function):
                print("Is Func")
                _var = env[0]
                _type_dict = env[1]
                _env = env[2]
                _params = gen_params(type_dict, env)
                print(_params)
                _size = env[3]
                print(_size)
                f = gen_func(_params, _var, _type_dict, _env, _size)
                env[item] = f
                type_dict[item] = Call
            if(type_dict[item] == Let):
                print("Is Let")
                _ntype = env[item][0]
                _bind_var = env[item][1]
                _var = env[item][2]
                _dict = env[item][3]
                _env = env[item][4]
                _bind_var = bind(_ntype, _var, _dict, _env, params)
                env[item] = _bind_var
                type_dict[item] = Var
            if(type_dict[item] == Call):
                print("Is Call")
                name = env[item][0]
                _func = env[item][1]
                _args = env[item][2]
                _kwargs = env[item][3]
                arg_list = []
                for _var in _args:
                    if _var in params:
                        arg_list.append(_var)
                    else:
                        arg_list.append(env[_var])
                if(len(arg_list) != 0):
                    env[item] = _func(*arg_list, **_kwargs)
                else:
                    env[item] = _func(**_kwargs)
        return env[item]
    return func


def model_extent(func, main=False):
    length = 0
    if isinstance(func, Call):
        length = 1
        for arg in func.args:
            if(isinstance(arg, Call)):
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
    if isinstance(func, Tuple):
        return 1  # Anything past this in new scope
    else:
        return 0


def gen_schedule(args, func):
    return hcl.create_schedule(args, func)

# creating relay_to_hcl parser


def relay_parser(model, shape, frontend='keras', dtype=hcl.Float()):
    hcl.init(dtype)
    if frontend == 'keras':
        relay_model = keras.models.load_model(model)
        module, params = relay_front.from_keras(relay_model, shape)
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
        if isinstance(node, Function):
            name = "%" + str(place)
            print("Function: ", name)
            var = [name]
            type_dict = {name: Function}
            env = {}
            temp_var, temp_type, temp_env = parse_rec(node.body, place - 1)
            if(init):
                var = temp_var
                type_dict = temp_type
                env = temp_env
            else:
                size = model_extent(node)
                env = update_if(
                    env, {
                        name: (
                            full_flatten(temp_var), temp_type, temp_env, size)})
        elif isinstance(node, Var):
            name = node.name_hint
            var = [name]
            type_dict = {name: Var}
            ty = node.type_annotation
            env = {}
            if node.name_hint in shape:
                dtype = ty.dtype
                env[name] = hcl.placeholder(shape[name], name, dtype)
            else:
                env[name] = getType(ty, name)
            print("Var: " + name)
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
                env[name] = (name, getType(ty, var_name), index)
            elif isinstance(tup, Call):
                if(not hasattr(node.op, "name")):
                    opname = '%' + str(place - 1)
                else:
                    opname = node.op.name
                name = "get_" + opname
                var = [name]
                type_dict = {name: TupleGetItem}
                env = {}
                env[name] = {name, opname, index}
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
            temp_var, temp_type, temp_env = parse_rec(value, place)
            print(type(value))
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
                        print(kwargs[attr])
                env[name] = (Call,
                             bind_var,
                             temp_var,
                             temp_type,
                             temp_env)
            type_dict = update_if(type_dict, temp_type)
            temp_var, temp_type, temp_env = parse_rec(
                node.body, place - (val_len))
            var.append(temp_var)
            type_dict = update_if(type_dict, temp_type)
            env = update_if(env, temp_env)
        elif isinstance(node, If):
            print("If not instantiated yet")
        elif isinstance(node, Tuple):
            tup_inx = model_extent(node)
            print(tup_inx,place)
            name = "%" + str(place)
            var = [name]
            type_dict = {name: dict}
            env = {}
            tup_type_dict = {}
            tup = []
            tup_env = {}
            inx = 0
            for field in node.fields:
                if isinstance(field, Tuple):
                    inx = inx + 1
                temp_var, temp_type, temp_env = parse_rec(
                    field, tup_inx - inx + 1)  # assumption
                tup.append(temp_var)
                tup_type_dict.update(temp_type)
                tup_env.update(temp_env)
            env[name] = (name, tup, tup_type_dict, tup_env)
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
            for arg in node.args:
                print(type(arg))
                temp_var, temp_type, temp_env = parse_rec(arg, place - 1)
                if isinstance(arg, Var):
                    var.append(temp_var[0])
                    var = partial_flatten(var)
                    args.append(temp_env[fst(temp_var[0])])
                elif isinstance(arg, Call):
                    var.append(temp_var)
                    var = partial_flatten(var)
                    args.append(temp_env[temp_var[-1]][0])
                    temp_len += len(temp_env)
                    env.update(temp_env)
                elif isinstance(arg, TupleGetItem):
                    item,item_name = getItem(temp_env[temp_var[0]])
                    var.append(item_name)
                    var = partial_flatten(var)
                    args.append(temp_env[temp_var[0]][0])
                    print(temp_env)
                    env.update(temp_env)
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
                temp_var, temp_type, temp_env = parse_rec(node.op, place - 1)
                var.append(opname)
                type_dict.update({opname: Function})
                env[opname] = (temp_var, temp_type, temp_env)
        return var, type_dict, env
    out_var, out_type, out_env = parse_rec(body, place_num, True)
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
    for i in _param:
        print(type(i))
    func = gen_func(_param, out_var, out_type, out_env, place_num)
    _inputs = []
    if(params is None):
        params = in_params
    for var in params:
        _inputs.append(hcl.asarray(params[var].asnumpy()))
    print("here")
    s = gen_schedule(_param, func)
    return hcl.build(s), _inputs
