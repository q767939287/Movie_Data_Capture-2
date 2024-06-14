# -*- coding: utf-8 -*-
# build-in lib
import os.path
import os
import re
import uuid
import json
import time
import typing
from unicodedata import category
from concurrent.futures import ThreadPoolExecutor

# third party lib
import requests
from requests.adapters import HTTPAdapter
import mechanicalsoup
from pathlib import Path
from urllib3.util.retry import Retry
from lxml import etree
from cloudscraper import create_scraper
from scrapinglib import httprequest

# project wide
import config


def get_xpath_single(html_code: str, xpath):
    html = etree.fromstring(html_code, etree.HTMLParser())
    result1 = str(html.xpath(xpath)).strip(" ['']")
    return result1

G_USER_AGENT = r'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.133 Safari/537.36'

G_DEFAULT_TIMEOUT = 10  # seconds

# def get_javlib_cookie() -> [dict, str]:
#     import cloudscraper
#     switch, proxy, timeout, retry_count, proxytype = config.getInstance().proxy()
#     proxies = get_proxy(proxy, proxytype)
#
#     raw_cookie = {}
#     user_agent = ""
#
#     # Get __cfduid/cf_clearance and user-agent
#     for i in range(retry_count):
#         try:
#             if switch == 1 or switch == '1':
#                 raw_cookie, user_agent = cloudscraper.get_cookie_string(
#                     "http://www.javlibrary.com/",
#                     proxies=proxies
#                 )
#             else:
#                 raw_cookie, user_agent = cloudscraper.get_cookie_string(
#                     "http://www.javlibrary.com/"
#                 )
#         except requests.exceptions.ProxyError:
#             print("[-] ProxyError, retry {}/{}".format(i + 1, retry_count))
#         except cloudscraper.exceptions.CloudflareIUAMError:
#             print("[-] IUAMError, retry {}/{}".format(i + 1, retry_count))
#
#     return raw_cookie, user_agent


def translate(
        src: str,
        target_language: str = config.getInstance().get_target_language(),
        engine: str = config.getInstance().get_translate_engine(),
        app_id: str = "",
        key: str = "",
        delay: int = 0,
) -> str:
    """
    translate japanese kana to simplified chinese
    翻译日语假名到简体中文
    :raises ValueError: Non-existent translation engine
    """
    trans_result = ""
    # 中文句子如果包含&等符号会被谷歌翻译截断损失内容，而且中文翻译到中文也没有意义，故而忽略，只翻译带有日语假名的
    if (is_japanese(src) == False) and ("zh_" in target_language):
        return src
    if engine == "google-free":
        gsite = config.getInstance().get_translate_service_site()
        if not re.match(r'^translate\.google\.(com|com\.\w{2}|\w{2})$', gsite):
            gsite = 'translate.google.cn'
        url = (
            f"https://{gsite}/translate_a/single?client=gtx&dt=t&dj=1&ie=UTF-8&sl=auto&tl={target_language}&q={src}"
        )
        result = httprequest.get(url=url, return_type="object")
        if not result.ok:
            print('[-]Google-free translate web API calling failed.')
            return ''

        translate_list = [i["trans"] for i in result.json()["sentences"]]
        trans_result = trans_result.join(translate_list)
    elif engine == "azure":
        url = "https://api.cognitive.microsofttranslator.com/translate?api-version=3.0&to=" + target_language
        headers = {
            'Ocp-Apim-Subscription-Key': key,
            'Ocp-Apim-Subscription-Region': "global",
            'Content-type': 'application/json',
            'X-ClientTraceId': str(uuid.uuid4())
        }
        body = json.dumps([{'text': src}])
        result = httprequest.post(url=url, query=body, extra_headers=headers)
        translate_list = [i["text"] for i in result.json()[0]["translations"]]
        trans_result = trans_result.join(translate_list)
    elif engine == "deeplx":
        url = config.getInstance().get_translate_service_site()
        res = requests.post(f"{url}/translate", json={
            'text': src,
            'source_lang': 'auto',
            'target_lang': target_language,
        })
        if res.text.strip():
            trans_result = res.json().get('data')
    else:
        raise ValueError("Non-existent translation engine")

    time.sleep(delay)
    return trans_result


def load_cookies(cookie_json_filename: str) -> typing.Tuple[typing.Optional[dict], typing.Optional[str]]:
    """
    加载cookie,用于以会员方式访问非游客内容

    :filename: cookie文件名。获取cookie方式：从网站登录后，通过浏览器插件(CookieBro或EdittThisCookie)或者直接在地址栏网站链接信息处都可以复制或者导出cookie内容，以JSON方式保存

    # 示例: FC2-755670 url https://javdb9.com/v/vO8Mn
    # json 文件格式
    # 文件名: 站点名.json，示例 javdb9.json
    # 内容(文件编码:UTF-8)：
    {
        "over18":"1",
        "redirect_to":"%2Fv%2FvO8Mn",
        "remember_me_token":"***********",
        "_jdb_session":"************",
        "locale":"zh",
        "__cfduid":"*********",
        "theme":"auto"
    }
    """
    filename = os.path.basename(cookie_json_filename)
    if not len(filename):
        return None, None
    path_search_order = (
        Path.cwd() / filename,
        Path.home() / filename,
        Path.home() / f".mdc/{filename}",
        Path.home() / f".local/share/mdc/{filename}"
    )
    cookies_filename = None
    try:
        for p in path_search_order:
            if p.is_file():
                cookies_filename = str(p.resolve())
                break
        if not cookies_filename:
            return None, None
        return json.loads(Path(cookies_filename).read_text(encoding='utf-8')), cookies_filename
    except:
        return None, None


def file_modification_days(filename: str) -> int:
    """
    文件修改时间距此时的天数
    """
    mfile = Path(filename)
    if not mfile.is_file():
        return 9999
    mtime = int(mfile.stat().st_mtime)
    now = int(time.time())
    days = int((now - mtime) / (24 * 60 * 60))
    if days < 0:
        return 9999
    return days


def file_not_exist_or_empty(filepath) -> bool:
    return not os.path.isfile(filepath) or os.path.getsize(filepath) == 0


def is_japanese(raw: str) -> bool:
    """
    日语简单检测
    """
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\uFF66-\uFF9F]', raw, re.UNICODE))


def download_one_file(args) -> str:
    """
    download file save to given path from given url
    wrapped for map function
    """

    (url, save_path, json_headers) = args
    if json_headers is not None:
        filebytes = httprequest.get(url, return_type='content', json_headers=json_headers['headers'])
    else:
        filebytes = httprequest.get(url, return_type='content')
    if isinstance(filebytes, bytes) and len(filebytes):
        with save_path.open('wb') as fpbyte:
            if len(filebytes) == fpbyte.write(filebytes):
                return str(save_path)


def parallel_download_files(dn_list: typing.Iterable[typing.Sequence], parallel: int = 0, extra_headers=None):
    """
    download files in parallel 多线程下载文件

    用法示例: 2线程同时下载两个不同文件，并保存到不同路径，路径目录可未创建，但需要具备对目标目录和文件的写权限
    parallel_download_files([
    ('https://site1/img/p1.jpg', 'C:/temp/img/p1.jpg'),
    ('https://site2/cover/n1.xml', 'C:/tmp/cover/n1.xml')
    ])

    :dn_list: 可以是 tuple或者list: ((url1, save_fullpath1),(url2, save_fullpath2),) fullpath可以是str或Path
    :parallel: 并行下载的线程池线程数，为0则由函数自己决定
    """
    mp_args = []
    for url, fullpath in dn_list:
        if url and isinstance(url, str) and url.startswith('http') \
                and fullpath and isinstance(fullpath, (str, Path)) and len(str(fullpath)):
            fullpath = Path(fullpath)
            fullpath.parent.mkdir(parents=True, exist_ok=True)
            mp_args.append((url, fullpath, extra_headers))
    if not len(mp_args):
        return []
    if not isinstance(parallel, int) or parallel not in range(1, 200):
        parallel = min(5, len(mp_args))
    with ThreadPoolExecutor(parallel) as pool:
        results = list(pool.map(download_one_file, mp_args))
    return results


def delete_all_elements_in_list(string: str, lists: typing.Iterable[str]):
    """
    delete same string in given list
    """
    new_lists = []
    for i in lists:
        if i != string:
            new_lists.append(i)
    return new_lists


def delete_all_elements_in_str(string_delete: str, string: str):
    """
    delete same string in given list
    """
    for i in string:
        if i == string_delete:
            string = string.replace(i, "")
    return string


# print format空格填充对齐内容包含中文时的空格计算
def cn_space(v: str, n: int) -> int:
    return n - [category(c) for c in v].count('Lo')


"""
Usage: python ./ADC_function.py https://cn.bing.com/
Purpose: benchmark get_html_session
         benchmark get_html_by_scraper
         benchmark get_html_by_browser
         benchmark get_html
TODO: may be this should move to unittest directory
"""
if __name__ == "__main__":
    import sys
    import timeit
    from http.client import HTTPConnection

    def benchmark(times: int, url):
        print(f"HTTP GET Benchmark times:{times} url:{url}")
        tm = timeit.timeit(f"_ = session1.get('{url}')",
                           "from __main__ import get_html_session;session1=get_html_session()",
                           number=times)
        print(f' *{tm:>10.5f}s get_html_session() Keep-Alive enable')
        tm = timeit.timeit(f"_ = scraper1.get('{url}')",
                           "from __main__ import get_html_by_scraper;scraper1=get_html_by_scraper()",
                           number=times)
        print(f' *{tm:>10.5f}s get_html_by_scraper() Keep-Alive enable')
        tm = timeit.timeit(f"_ = browser1.open('{url}')",
                           "from __main__ import get_html_by_browser;browser1=get_html_by_browser()",
                           number=times)
        print(f' *{tm:>10.5f}s get_html_by_browser() Keep-Alive enable')
        tm = timeit.timeit(f"_ = get_html('{url}')",
                           "from __main__ import get_html",
                           number=times)
        print(f' *{tm:>10.5f}s get_html()')

    # target_url = "https://www.189.cn/"
    target_url = "http://www.chinaunicom.com"
    HTTPConnection.debuglevel = 1
    html_session = httprequest.request_session()
    _ = html_session.get(target_url)
    HTTPConnection.debuglevel = 0

    # times
    t = 100
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    benchmark(t, target_url)
