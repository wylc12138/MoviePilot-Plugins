import os
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import List, Tuple, Dict, Any

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.metainfo import MetaInfoPath
from app.db.transferhistory_oper import TransferHistoryOper
from app.helper.nfo import NfoReader
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaType
from app.utils.system import SystemUtils


class LibraryScraper(_PluginBase):
    # 插件名称
    plugin_name = "媒体库刮削重构版"
    # 插件描述
    plugin_desc = "定时对媒体库进行刮削，补齐缺失元数据和图片。"
    # 插件图标
    plugin_icon = "scraper.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "wylc12138"
    # 作者主页
    author_url = "https://github.com/wylc12138"
    # 插件配置项ID前缀
    plugin_config_prefix = "libraryscraper_reconfiguration_"
    # 加载顺序
    plugin_order = 7
    # 可使用的用户级别
    user_level = 1

    # 私有属性
    transferhis = None
    _scheduler = None
    _scraper = None
    # 最近天数
    _offset_days = "0"
    # 限速开关
    _enabled = False
    _onlyonce = False
    _cron = None
    _mode = ""
    _scraper_paths = ""
    _exclude_paths = ""
    # 退出事件
    _event = Event()

    def init_plugin(self, config: dict = None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._mode = config.get("mode") or ""
            self._scraper_paths = config.get("scraper_paths") or ""
            self._exclude_paths = config.get("exclude_paths") or ""
            self._offset_days = config.get("offset_days")

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:
            self.transferhis = TransferHistoryOper()

            if self._onlyonce:
                logger.info(f"媒体库刮削服务，立即运行一次")
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(func=self.__libraryscraper, trigger='date',
                                        run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="媒体库刮削")
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "mode": self._mode,
                    "scraper_paths": self._scraper_paths,
                    "exclude_paths": self._exclude_paths,
                    "offset_days": self._offset_days,
                })
                if self._scheduler.get_jobs():
                    # 启动服务
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._cron:
            return [{
                "id": "LibraryScraperReconfiguration",
                "name": "媒体库刮削-重构版",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.__libraryscraper,
                "kwargs": {}
            }]
        elif self._enabled:
            return [{
                "id": "LibraryScraperReconfiguration",
                "name": "媒体库刮削-重构版",
                "trigger": CronTrigger.from_crontab("0 0 */7 * *"),
                "func": self.__libraryscraper,
                "kwargs": {}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'mode',
                                            'label': '刮削模式',
                                            'items': [
                                                {'title': '仅刮削缺失元数据和图片', 'value': ''},
                                                {'title': '覆盖所有元数据和图片', 'value': 'force_all'},
                                                {'title': '覆盖所有元数据', 'value': 'force_nfo'},
                                                {'title': '覆盖所有图片', 'value': 'force_image'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "offset_days",
                                            "label": "几天内",
                                        },
                                    }
                                ],
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'scraper_paths',
                                            'label': '削刮路径',
                                            'rows': 5,
                                            'placeholder': '每一行一个目录'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'exclude_paths',
                                            'label': '排除路径',
                                            'rows': 2,
                                            'placeholder': '每一行一个目录'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '刮削路径后拼接#电视剧/电影，强制指定该媒体路径媒体类型。'
                                                    '不加默认根据文件名自动识别媒体类型。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "cron": "0 0 */7 * *",
            "mode": "",
            "scraper_paths": "",
            "err_hosts": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def __libraryscraper(self):
        """
        开始刮削媒体库
        """
        if not self._scraper_paths:
            return
        # 排除目录
        exclude_paths = self._exclude_paths.split("\n")
        # 已选择的目录
        paths = self._scraper_paths.split("\n")
        for path in paths:
            if not path:
                continue
            # 强制指定该路径媒体类型
            mtype = None
            if str(path).count("#") == 1:
                mtype = next(
                    (mediaType for mediaType in MediaType.__members__.values() if
                     mediaType.value == str(str(path).split("#")[1])),
                    None)
                path = str(path).split("#")[0]
            scraper_path = Path(path)
            if not scraper_path.exists():
                logger.warning(f"媒体库刮削路径不存在：{path}")
                continue
            logger.info(f"开始刮削媒体库：{path} {mtype} ...")
            # 遍历所有文件
            files = SystemUtils.list_files(scraper_path, settings.RMT_MEDIAEXT)
            for file_path in files:
                if self._event.is_set():
                    logger.info(f"媒体库刮削服务停止")
                    return
                # 排除目录
                exclude_flag = False
                for exclude_path in exclude_paths:
                    try:
                        if file_path.is_relative_to(Path(exclude_path)):
                            exclude_flag = True
                            break
                    except Exception as err:
                        print(str(err))
                if exclude_flag:
                    logger.debug(f"{file_path} 在排除目录中，跳过 ...")
                    continue
                # 开始刮削文件
                self.__scrape_file(file=file_path, mtype=mtype)
            logger.info(f"媒体库 {path} 刮削完成")

    def __scrape_file(self, file: Path, mtype: MediaType = None):
        """
        削刮一个目录，该目录必须是媒体文件目录
        """
        # 识别元数据
        meta_info = MetaInfoPath(file)
        # 强制指定类型
        if mtype:
            meta_info.type = mtype

        # 是否刮削
        force_nfo = self._mode in ["force_all", "force_nfo"]
        force_img = self._mode in ["force_all", "force_image"]

        # 优先读取本地nfo文件
        tmdbid = None
        if meta_info.type == MediaType.MOVIE:
            # 电影
            movie_nfo = file.parent / "movie.nfo"
            if movie_nfo.exists():
                tmdbid = self.__get_tmdbid_from_nfo(movie_nfo)
            file_nfo = file.with_suffix(".nfo")
            if not tmdbid and file_nfo.exists():
                tmdbid = self.__get_tmdbid_from_nfo(file_nfo)
        else:
            # 电视剧
            tv_nfo = file.parent.parent / "tvshow.nfo"
            if tv_nfo.exists():
                tmdbid = self.__get_tmdbid_from_nfo(tv_nfo)
        if tmdbid:
            # 按TMDBID识别
            logger.info(f"读取到本地nfo文件的tmdbid：{tmdbid}")
            mediainfo = self.chain.recognize_media(tmdbid=tmdbid, mtype=meta_info.type)
        else:
            # 按名称识别
            mediainfo = self.chain.recognize_media(meta=meta_info)
        if not mediainfo:
            logger.warn(f"未识别到媒体信息：{file}")
            return

        # 如果未开启新增已入库媒体是否跟随TMDB信息变化则根据tmdbid查询之前的title
        if not settings.SCRAP_FOLLOW_TMDB:
            transfer_history = self.transferhis.get_by_type_tmdbid(tmdbid=mediainfo.tmdb_id,
                                                                   mtype=mediainfo.type.value)
            if transfer_history:
                mediainfo.title = transfer_history.title

        self.browse_path_and_delete_nfo(file.parent)

        # 获取图片
        self.chain.obtain_images(mediainfo)
        # 刮削
        self.chain.scrape_metadata(path=file,
                                   mediainfo=mediainfo,
                                   transfer_type=settings.TRANSFER_TYPE,
                                   force_nfo=force_nfo,
                                   force_img=force_img)

    @staticmethod
    def __get_tmdbid_from_nfo(file_path: Path):
        """
        从nfo文件中获取信息
        :param file_path:
        :return: tmdbid
        """
        if not file_path:
            return None
        xpaths = [
            "uniqueid[@type='Tmdb']",
            "uniqueid[@type='tmdb']",
            "uniqueid[@type='TMDB']",
            "tmdbid"
        ]
        try:
            reader = NfoReader(file_path)
            for xpath in xpaths:
                tmdbid = reader.get_element_value(xpath)
                if tmdbid:
                    return tmdbid
        except Exception as err:
            logger.warn(f"从nfo文件中获取tmdbid失败：{str(err)}")
        return None

    @staticmethod
    def __get_date(offset_day):
        now_time = datetime.now()
        end_time = now_time + timedelta(days=offset_day)
        # 返回一个日期对象
        return end_time.date()

    @staticmethod
    def get_all_subfolders(path: Path):
        """获取指定路径下所有文件夹路径"""
        subfolders = []

        # 递归遍历文件夹
        for root, dirs, files in os.walk(path):
            for dir_name in dirs:
                subfolder_path = os.path.join(root, dir_name)
                subfolders.append(subfolder_path)

        return subfolders

    @staticmethod
    def is_video_file(file_path):
        # 常见视频文件扩展名
        video_extensions = {'.mp4', '.mkv', '.flv', '.avi', '.mov', '.wmv', '.m4v', '.mpg', '.mpeg', '.3gp', '.webm'}

        # 获取文件扩展名并转换为小写进行匹配
        _, ext = os.path.splitext(file_path)
        return ext.lower() in video_extensions

    @staticmethod
    def get_file_modification_date(file_path):
        """获取文件的修改时间戳"""
        timestamp = os.path.getmtime(file_path)
        # 将时间戳转换为 datetime 对象
        modification_datetime = datetime.fromtimestamp(timestamp)
        # 返回一个 date 对象
        return modification_datetime.date()

    def browse_path(self, path: Path):
        """遍历目录下的文件夹，获取视频文件入库时间，然后删除视频文件对应的nfo文件，强制覆盖元数据和图片"""
        overwrite = True if self._mode else False
        if not overwrite:  # 未开启覆盖所有元数据和图片，不删除nfo文件
            return
        # 获取指定天数之前的日期
        end_date = self.__get_date(-int(self._offset_days))
        subfolder_path = self.get_all_subfolders(path)
        # 遍历所有文件夹下面的所有文件，并判断是否为视频文件且修改日期在指定天数内
        for subfolder in subfolder_path:
            for file in os.listdir(subfolder):
                filepath = os.path.join(subfolder, file)
                # 检查是否是文件（排除目录）
                if os.path.isfile(filepath):
                    if self.is_video_file(filepath):
                        file_date = self.get_file_modification_date(filepath)
                        if file_date >= end_date:
                            # 获取文件的扩展名
                            _, extension = os.path.splitext(filepath)
                            # 获取文件名对应的nfo文件
                            nfo_path = filepath.replace(extension, "nfo")
                            logger.info(f"找到符合条件的nfo文件：{nfo_path}")
                            # 删除文件名对应的nfo文件
                            os.remove(nfo_path)

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))
