# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.http import StreamingHttpResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
import CaliperServer.settings as settings
from shared.Response import Response
from shared.log import logger
import os, re, json
import operator
from django.contrib import auth
from account.models import UserProfile
from sso.apiclient import client
import urllib
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from .sso import REMOTE_SSO_LOGIN_URL, REMOTE_SSO_CHANGEPWD_URL, REMOTE_SSO_LOGOUT_URL, REMOTE_SSO_SIGNUP_URL, \
    logined_users,REMOTE_SSO_CHANGEMAIL_URL
from sso.authbackend import SSOAuthBackend
from sso.utility import form_redirect
from .permission import login_required
from shared import Contants
from shared.crypto import *
from django.shortcuts import HttpResponse, redirect
from django.utils.html import escape



def main(request):
    from CaliperServer.settings import downloadPath
    versions = []
    for path in os.listdir(downloadPath):
        if path.endswith('.zip'):
            shotName,ext = os.path.splitext(path)
            version_txt_path = os.path.join(downloadPath, shotName+'.txt')
            version_msg = []
            if os.path.exists(version_txt_path):
                try:
                    f = open(version_txt_path)
                    for line in f:
                        version_msg.append(line.strip())
                    f.close()
                    # with open(version_txt_path) as f:
                    #     version_msg = escape(f.readline)
                except:
                    pass
            version = re.search('v(\S+)\.', path)
            if version is not None:
                obj = {'version': version.group(1), 'path': os.path.join(downloadPath, path),'msg':version_msg}
                versions.append(obj)
    versions.sort(key=operator.itemgetter('version'), reverse=True)
    logger.debug(versions)

    data = {'versions': json.dumps(versions)}

    return render(request, "main.html", data)


def download(req):
    from CaliperServer.settings import downloadPath
    try:
        filePath = ''
        version = req.GET.get('version')
        # obJson = req.body
        # params = json.loads(obJson)
        # version = params['version']
        for path in os.listdir(downloadPath):
            if path.endswith('.zip'):
                v = re.search('v(\S+)\.', path)
                if v is not None and v.group(1) == str(version):
                    filePath = os.path.join(downloadPath, path)
                    print filePath
    except Exception as e:
        logger.error(str(e))
        return Response.CustomJsonResponse(Response.CODE_FAILED, 'fail')
    if filePath is not None:
        splits = filePath.split("/")
        fileName = splits[len(splits) - 1]
        response = StreamingHttpResponse(file_iterator(filePath))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="{0}"'.format(fileName)
        return response


def file_iterator(filename, chunk_size=512):
    with open(filename, "rb") as f:
        while True:
            c = f.read(chunk_size)
            if c:
                yield c
            else:
                break


def login0(req):
    user = UserProfile.objects.get(username="admin")
    auth.login(req, user)
    return HttpResponseRedirect("/task/list")


@login_required
def getuserinfo(req):
    # username=req.GET.get('username')
    # if not username :
    #     return HttpResponse(status=500,content='传参数非法')
    # try:
    #     item=UserProfile.objects.get(username=username)
    #     data = {'username': item.name, 'add': item.address, 'time': item.date_joined, 'mail': item.email, \
    #             'userid': item.username, 'org': item.company, 'role': item.role, 'phone': item.telphone,
    #             'last_login': item.last_login,'avatar':item.avatar}
    # except:
    #     return HttpResponse(status=404, content='未找到')

    # return HttpResponse(status=200)
    return render(req, "userinfo.html", {'isShowBack': True})

@login_required
def save(req):
    try:
        obJson = req.body
        server = json.loads(obJson)
        user = UserProfile.objects.get(id=req.user.id)
        user.name = server['name']
        user.company = server['company']
        user.address = server['address']
        user.telphone = server['phone']
        user.save()
    except Exception as e:
        logger.debug(str(e))
        return Response.CustomJsonResponse(Response.CODE_FAILED, 'fail')
    return Response.CustomJsonResponse(Response.CODE_SUCCESS, 'ok')


@csrf_exempt
@login_required
def upload(req):
    # try:
    #     file = req.FILES['file']
    #     # filename=str(file)
    #     item = UserProfile.objects.get(username=req.user.username)
    # except:
    #     return HttpResponse(status=500, content='database connect failed')
    # item.avatar = file
    # item.save()
    # return HttpResponse(status=200)

    if req.method == 'POST':
        file = req.FILES.get('file', None)
        logger.debug("file count %s", file.name)
        if not file:
            logger.debug("file is not exist")
            return HttpResponse(status=500)
        else:
            try:
                user = UserProfile.objects.get(username=req.user.username)
                if user.avatar.name == '':
                    oldPath = ''
                else:
                    oldPath = user.avatar.path
                user.avatar = file
                user.save()
                if user.avatar.path != oldPath and oldPath != '':
                    os.remove(oldPath)
            except Exception as e:
                logger.debug("avatar exception %s", str(e))
                return HttpResponse(status=500)

                # form = UploadFileForm(request.POST, request.FILES)
                # if form.is_valid():
                #     handle_uploaded_file(request.FILES['file'])
                #     return HttpResponseRedirect('/success/url/')
                # else:
                # form = UploadFileForm()
    data = {
        'avatar': user.avatar.name
    }
    return Response.CustomJsonResponse(Response.CODE_SUCCESS, 'ok', data)


################sso



@csrf_exempt
def auth_callback(request):
    """
    单点登录后的回调（由SSO服务器发起）
    :param request:
    :return:
    """
    auth_token = request.POST.get("auth_token")
    redirect = request.GET.get("redirect", settings.LOGIN_REDIRECT_URL)

    error, user, user_info = SSOAuthBackend.authenticate(auth_token)
    if not error:
        try:
            if not user:  # 这种情况表明用户在其他site注册，并且首次登陆本site
                role = Contants.ROLE_USER
                if user_info is not None and user_info['admin'] is not None and request.get_host().lower() in user_info['admin'].lower():
                    role = Contants.ROLE_ADMIN
                user = UserProfile(username=user_info['username'], email=user_info['email'], role=role)
                user.save()
            auth.login(request, user)  # create session, write cookies
            logined_users[auth_token] = user  # 存入全局变量中
            request.session["auth_token"] = auth_token  # 存入session
            return HttpResponseRedirect(redirect)
        except Exception as e:
            logger.info(str(e))
            return HttpResponse('sso authenticate failed')
    else:
        raise PermissionDenied


@csrf_exempt
def signup_callback(request):
    """
    注册成功后的回调（由SSO服务器发起）
    :param request:
    :return:
    """
    auth_token = request.POST.get("auth_token")
    redirect = request.GET.get("redirect", settings.LOGIN_REDIRECT_URL)

    error, user, user_info = SSOAuthBackend.authenticate(auth_token)
    if error or user or not user_info:
        raise PermissionDenied
    else:
        user = UserProfile(username=user_info['username'], email=user_info['email'])
        user.save()

        auth.login(request, user)  # create session, write cookies
        logined_users[auth_token] = user  # 存入全局变量中
        request.session["auth_token"] = auth_token  # 存入session
        return HttpResponseRedirect(redirect)


def logout_notify(request):
    """
    单点登出的回调（由SSO服务器发起）
    :param request:
    :return:
    """
    auth_token = request.GET.get("auth_token")
    print "logout_notify:" + auth_token, auth_token in logined_users.keys()
    if auth_token in logined_users.keys():
        logined_users.pop(auth_token)  # 从全局删除
        auth.logout(request)
        # if request.session.exists("auth_token"):
        #     del request.session['auth_token']
    else:
        print auth_token + ' not in logined_users.keys().'
    return JsonResponse({"msg": "ok"})


@csrf_exempt
def changepwd_callback(request):
    """
    修改密码后的回调（由SSO服务器发起）
    :param request:
    :return:
    """
    auth_token = request.POST.get("auth_token")
    redirect = request.GET.get("redirect", settings.LOGIN_REDIRECT_URL)

    error, user, user_info = SSOAuthBackend.authenticate(auth_token)
    if not error:
        if not user:  # 这种情况表明用户在其他site注册，并且首次登陆本site
            user = UserProfile(username=user_info['username'], email=user_info['email'])
            user.save()
        auth.login(request, user)  # create session, write cookies
        logined_users[auth_token] = user  # 存入全局变量中
        request.session["auth_token"] = auth_token  # 存入session
        return HttpResponseRedirect(redirect)
    else:
        raise PermissionDenied


@login_required
def logout(request):
    """
    登出
    :param request:
    :return:
    """
    auth_token = request.session.get('auth_token', None)
    if auth_token:
        try:
            del request.session['auth_token']
            client_ip = request.META.get("REMOTE_ADDR")
            code, result = client.send_request(REMOTE_SSO_LOGOUT_URL + "?" +
                                               urllib.urlencode({"auth_token": auth_token, "client_ip": client_ip}))
            print result['msg']
        except Exception as e:
            print e

    if auth_token in logined_users.keys():
        logined_users.pop(auth_token)  # 从全局删除
    auth.logout(request)
    return HttpResponseRedirect('/')


def login(request):
    """
    登录页面
    :param request:
    :return:
    """
    server = settings.SSO_API_AUTH_SETTING["url"]
    callback = request.build_absolute_uri(reverse("authcallback") +
                                          "?redirect=%s" % request.GET.get("next", settings.LOGIN_REDIRECT_URL))

    return form_redirect(server + REMOTE_SSO_LOGIN_URL, apikey=settings.SSO_API_AUTH_SETTING["apikey"],
                         callback=callback)


def signup(request):
    """
    注册页面
    :param request:
    :return:
    """
    server = settings.SSO_API_AUTH_SETTING["url"]
    callback = request.build_absolute_uri(reverse("signupcallback") +
                                          "?redirect=%s" % request.GET.get("next", settings.LOGIN_REDIRECT_URL))

    return form_redirect(server + REMOTE_SSO_SIGNUP_URL, apikey=settings.SSO_API_AUTH_SETTING["apikey"],
                         callback=callback)


def change_pwd(request):
    """
    修改密码页面
    :param request:
    :return:
    """
    server = settings.SSO_API_AUTH_SETTING["url"]
    callback = request.build_absolute_uri(reverse("changepwdcallback") +
                                          "?redirect=%s" % request.GET.get("next", settings.USER_REDIRECT_URL))

    return form_redirect(server + REMOTE_SSO_CHANGEPWD_URL, apikey=settings.SSO_API_AUTH_SETTING["apikey"],
                         callback=callback)


def change_email(request):
    """
    修改密码页面
    :param request:
    :return:
    """
    server = settings.SSO_API_AUTH_SETTING["url"]
    callback = request.build_absolute_uri(reverse("changemailcallback") +
                                          "?redirect=%s" % request.GET.get("next", settings.USER_REDIRECT_URL))

    return form_redirect(server + REMOTE_SSO_CHANGEMAIL_URL, apikey=settings.SSO_API_AUTH_SETTING["apikey"],
                         username=request.user.username,
                         callback=callback)

@csrf_exempt
def changemail_callback(request):
    """
    修改邮箱后的回调（由SSO服务器发起）
    :param request:
    :return:
    """
    auth_token = request.POST.get("auth_token")
    email = request.POST.get("email")
    redirect = request.GET.get("redirect", settings.USER_REDIRECT_URL)

    error, user, user_info = SSOAuthBackend.authenticate(auth_token)
    if not error:
        UserProfile.objects.filter(username=user_info['username']).update(email=email)
        user = UserProfile.objects.get(username=user_info['username'])
        auth.login(request, user)  # create session, write cookies
        logined_users[auth_token] = user  # 存入全局变量中
        request.session["auth_token"] = auth_token  # 存入session
        return HttpResponseRedirect(redirect)
    else:
        raise PermissionDenied


@csrf_exempt
def lock_notify(request):
    """
    账户被锁定后的通知（由SSO服务器发起）
    :param request:
    :return:
    """
    day = request.GET.get("d", 0)
    account = request.GET.get("account", None)
    singer = request.GET.get("singer", None)
    if day and account and singer:
        isOk = verify(account,singer)
        if not isOk:
            return HttpResponse('参数值签名有误', status=403)
        user = UserProfile.objects.filter(username=account).first()
        if user is None:
            return HttpResponse('用户名不存在', status=403)
        if day == u'1':  # 锁定当天
            for token, user in logined_users.items():
                if user.username == account:
                    logined_users.pop(token)
                    break
            # user.is_active = False
            # user.save()
            UserProfile.objects.filter(username=account).update(is_active=False)
            return HttpResponse('ok', status=200)
        elif day == u'7':  # 锁定7天
            # TODO
            print 7
        else:
            return HttpResponse('参数值有误', status=403)
        return HttpResponseRedirect(redirect)
    else:
        return HttpResponse('参数缺失', status=403)

@csrf_exempt
def unlock_notify(request):
    """
    账户解锁后的通知（由SSO服务器发起）
    :param request:
    :return:
    """
    account = request.GET.get("account", None)
    singer = request.GET.get("singer", None)
    if account and singer:
        isOk = verify(account,singer)
        if not isOk:
            return HttpResponse('参数值签名有误', status=403)
        user = UserProfile.objects.filter(username=account).first()
        if user is None:
            return HttpResponse('用户名不存在', status=403)

        # user.is_active = True
        # user.save()
        UserProfile.objects.filter(username=account).update(is_active=True)
        return HttpResponse('ok', status=200)
    else:
        return HttpResponse('参数缺失', status=403)


