import asyncio
import difflib
import os
import time
import datetime
import uuid
import requests
from pikpakapi import PikPakApi
import feedparser
import logging
import yaml
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class State(Enum):
    UNHANDLED = 1
    WAITING = 2
    HANDLING = 3


class AnimeInfo:
    title: str
    resourceLinks: str


class UserInfo:
    userName: str
    passwd: str
    waitTime: int


class RssInfo:
    animeName: str
    updateTime: str
    links: str
    State = State.UNHANDLED
    lastIndex: int = 0
    animeList: list[AnimeInfo] = []
    translationGroup: str
    uuid: str


def GetUserInfo() -> UserInfo:
    userInfo = UserInfo()
    with open('config.yml', 'r') as ymlfile:
        config = yaml.load(ymlfile, Loader=yaml.FullLoader)
    userInfo.userName = config['userName']
    userInfo.passwd = config['passwd']
    userInfo.waitTime = config['waitTime']
    return userInfo


def Download(url: str, path: str) -> None:
    response = requests.get(url, stream=True)

    # 检查响应状态码。
    if response.status_code != 200:
        raise RuntimeError(f"Error downloading file: {response.status_code}")

    # 打开要保存文件的路径。
    with open(path, "wb") as f:
        # 逐块下载文件并写入文件。
        for chunk in response.iter_content(chunk_size=1024):
            f.write(chunk)  # 检查文件是否已下载。
    if os.path.isfile(path):
        print("File downloaded successfully.")
    else:
        print("Error downloading file.")


def GetAnime(rss: RssInfo) -> list[AnimeInfo]:
    _uuid = rss.uuid
    # 创建Subscribe目录
    if not os.path.exists("./Subscribe"):
        os.makedirs("./Subscribe")

    # 检查_uuid+.rss是否存在
    rss_file = f"./Subscribe/{_uuid}.rss"
    new_rss_file = f"./Subscribe/{_uuid}.rss.tmp"
    diff_rss_file = f"./Subscribe/{_uuid}.rss.diff"
    final_rss_file: str

    # 下载rssLinks
    # 这里需要你添加下载rssLinks并保存为new_rss_file的代码
    Download(rss.links, new_rss_file)

    # 如果原始rss文件存在，比较差异并写入diff_rss_file
    if os.path.exists(rss_file):
        # 使用difflib比较两个文件的差异
        with open(rss_file, 'r', encoding='utf-8') as f1:
            with open(new_rss_file, 'r', encoding='utf-8') as f2:
                diff = difflib.unified_diff(f1.readlines(), f2.readlines(), fromfile=rss_file, tofile=new_rss_file)
                changes = list(diff)
                # 如果有差异，将差异写入diff_rss_file
                if changes:
                    with open(diff_rss_file, "w", encoding="utf-8") as f_diff:
                        f_diff.writelines(changes)
                        final_rss_file = diff_rss_file
                else:
                    return []
    else:
        # 如果原始rss文件不存在，直接将新的rss文件重命名为原始文件名
        final_rss_file = rss_file
    if os.path.exists(rss_file):
        os.remove(rss_file)
    os.rename(new_rss_file, rss_file)
    # 解析RSS内容
    p = feedparser.parse(final_rss_file)
    subrss = p['entries']
    Anime: list[AnimeInfo] = []
    for subr in subrss:
        anime = AnimeInfo()
        anime.title = subr['title']
        anime.title = anime.title.replace("/", "").replace("`", "").replace(":", "").replace("*", "").replace("?",
                                                                                                              "").replace(
            '"', "").replace("<", "").replace(">", "").replace("|", "")
        if anime.title.find(rss.translationGroup) != -1:
            anime.resourceLinks = subr['links'][1]['href']
            Anime.append(anime)

    if os.path.exists(new_rss_file):
        os.remove(new_rss_file)
    if os.path.exists(diff_rss_file):
        os.remove(diff_rss_file)
    return Anime


def GetCurrentTime() -> str:
    # 获取当前系统时间
    now = datetime.datetime.now()

    # 将时间格式化为 "sat 21:30:54"
    formatted_time = now.strftime("%a %H:%M:%S")

    # 打印格式化后的时间
    return formatted_time


def CompareTime(time1: str, time2: str) -> bool:
    # 解析时间字符串为datetime对象
    dt_format = "%a %H:%M:%S"
    dt1 = datetime.datetime.strptime(time1, dt_format)
    dt2 = datetime.datetime.strptime(time2, dt_format)

    # 比较时间
    if dt1.weekday() != dt2.weekday():
        return dt1.weekday() < dt2.weekday()
    else:
        return dt1.time() < dt2.time()


def RssReader() -> list[RssInfo]:
    with open(r"Task.yml", "rb") as f:
        tasks = yaml.load(f, Loader=yaml.FullLoader)
    # 创建一个列表来存储 RssInfo 对象
    listOfRss = []

    # 遍历 YAML 文件中的数据
    for item in tasks["Anime"]:
        # 创建一个 RssInfo 对象
        rssInfo = RssInfo()

        # 设置 RssInfo 对象的属性
        rssInfo.animeName = item["animeName"]
        rssInfo.translationGroup = item["translationGroup"]
        rssInfo.links = item["links"]

        # 将 RssInfo 对象添加到列表中
        listOfRss.append(rssInfo)

    # 打印 RssInfo 对象列表
    return listOfRss


def GenerateUUID(Symbol: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, Symbol))


async def PushAnime(client: PikPakApi, rssinfo: RssInfo) -> None:
    ids = await client.path_to_id(rssinfo.animeName, True)
    id = ids[0]['id']
    logger.info(f"Get anime info {rssinfo.animeName} from rss source")

    # 初始化索引值
    start_index = 0
    if rssinfo.lastIndex == 0:
        rssinfo.animeList = GetAnime(rssinfo)

        # 如果之前已经处理过部分动画信息，从上次中断的位置开始处理
    if rssinfo.State == State.HANDLING:
        start_index = rssinfo.lastIndex

    try:
        # 获取动画信息列表
        anime = rssinfo.animeList

        # 从上次中断的位置开始处理动画信息
        for i in range(start_index, len(anime)):
            ani = anime[i]
            logger.info(f"Title: {ani.title}")
            logger.info(f"Links: {ani.resourceLinks}")
            await client.offline_download(
                file_url=ani.resourceLinks,
                parent_id=id,
                name=ani.title
            )
            # 记录已处理的索引值
            rssinfo.lastIndex = i + 1

    except Exception as e:
        rssinfo.State = State.WAITING
        raise Exception(e)

    logger.info("Finished")
    rssinfo.lastIndex = 0
    rssinfo.animeList = []
    rssinfo.State = State.WAITING


async def UpdateAnime():
    logger.info("Service start")
    logger.info("Log in PikPak drive")
    userinfo = GetUserInfo()
    client = PikPakApi(
        username=userinfo.userName,
        password=userinfo.passwd,
    )
    await client.login()
    while True:
        try:
            rssinfo = RssReader()
            tasks = []
            for rss in rssinfo:
                if rss.State != State.HANDLING:
                    rss.State = State.HANDLING
                    rss.uuid = GenerateUUID(rss.animeName)
                    tasks.append(asyncio.create_task(PushAnime(client, rss)))

            # 并行处理多个RSS任务
            await asyncio.gather(*tasks)

            await asyncio.sleep(userinfo.waitTime)  # 等待30分钟后重新执行

        except Exception as e:
            logger.error(f"An error occurred: {e}")
            logger.info("Waiting for 5 seconds before retrying...")
            await asyncio.sleep(5)  # 等待5秒后重新执行


if __name__ == "__main__":
    print(RssReader())
    asyncio.run(UpdateAnime())
