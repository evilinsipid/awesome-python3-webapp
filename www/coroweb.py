#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import functools, asyncio, os, inspect, logging; logging.basicConfig(level=logging.INFO)
from urllib import parse
from aiohttp import web
from apis import APIError

def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator
    
def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator
    
def get_required_kw_args(fn):
    args = []
    # inspect.signature可显示所定义函数的参数
    # inspect.signature.parameters可获得所定义函数的参数
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        #param.kind：参数的种类；param.default：参数的默认值
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)
    
#获取命名关键字参数:
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)
    
#是否有命名关键字参数:
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        # inspect.Parameter.KEYWORD_ONLY 命名关键字参数
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True
            
#是否有关键字参数:
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        # inspect.Parameter.VAR_KEYWORD 关键字参数
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
            
#是否有request参数:
def has_request_arg(fn):
    params = inspect.signature(fn).parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        # inspect.Parameter.VAR_POSITIONAL 可变参数
        # 如果已找到'request'，并且函数参数为位置参数：
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found
    
class RequestHandler(object):
    
    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)
        
    async def __call__(self, request):
        kw = None
        # 'POST' and 'GET', 并把获取的值储存到kw
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST':
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type.')
                ct = request.content_type.lower()
                # startswith() 方法用于检查字符串是否是以指定子字符串开头，如果是则返回 True，否则返回 False
                # 以application/json的content-type传送数据，被传送的对象只需被json序列化。
                if ct.startswith('application/json'):
                    params = await request.json()
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                # 以application/x-www-form-urlencoded的方式传送数据。请求的内容需要以..=..&..=..的格式提交，在请求体内内容将会以”&”和“ = ”进行拆分。
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                # ?后的字符串
                qs = request.query_string
                if qs:
                    kw = dict()
                    # parse_qs(qs, keep_blank_values=False, strict_parsing=False, encoding='utf-8', errors='replace')
                    # 用来处理 "test=test&test2=test2&test2=test3" 类型的字符串,可解析为 {'test': ['test'], 'test2': ['test2', 'test3']}
                    # keep_blank_values 用来指定是否要保存空白符
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        if kw is None:
            kw = dict(**request.match_info)
        # 如果kw非空:
        else:
            # 如果没有关键字参数并且获取到命名关键字参数:
            if not self._has_var_kw_arg and self._named_kw_args:
                # remove all unamed kw:
                copy = dict()
                # 判断request的请求参数是否和函数的命名关键字参数一致，一致的保存到copy里
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request
        # check required kw:
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argumeny: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)
            
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))
    
# URL处理器
def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    # asyncio.iscoroutinefunction(fn) 判断是否为协程
    # inspect.isgeneratorfunction(fn) 判断是否为生成器函数
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join([str(x) for x in inspect.signature(fn).parameters.values()])))
    app.router.add_route(method, path, RequestHandler(app, fn))
    
def add_routes(app, module_name):
    # rfind() 返回字符串最后一次出现的位置，如果没有匹配项则返回-1
    n = module_name.rfind('.')
    if n == -1:
        # __import__(name, globals=None, locals=None, fromlist=[], level=0)
        #等同于 import 'module_name' as mod , globals() 和 locals() 指示全局应用
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n+1:]
        # __import__(module_name[:n], globals(), locals(), [name]等同于 from 'module_name[:n]' import name
        # from 'module_name[:n]' import name as mod
        # import 'module_name' as mod
                                                                        # *
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    for attr in dir(mod):
        # 排除__xxx__的模块
        if attr.startswith('_'):
            continue
        # fn = mod.attr
        fn = getattr(mod, attr)
        # 如果可调用:
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            # 如果有'__method__' 与 '__route__'属性:
            if method and path:
                add_route(app, fn)