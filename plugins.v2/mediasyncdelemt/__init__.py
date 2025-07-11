import os
import shutil
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app import schemas
from app.chain.storage import StorageChain
from app.chain.transfer import TransferChain
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.db.models.transferhistory import TransferHistory
from app.db.transferhistory_oper import TransferHistoryOper
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.helper.downloader import DownloaderHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType, EventType, MediaType, MediaImageType
from app.utils.system import SystemUtils


class MediaSyncDelEmt(_PluginBase):
    # 插件名称
    plugin_name = "EMBY同步删除"
    # 插件描述
    plugin_desc = "同步删除历史记录、源文件，原作者thsrite。"
    # 插件图标
    plugin_icon = "mediasyncdel.png"
    # 插件版本
    plugin_version = "1.9.9"
    # 插件作者
    plugin_author = "2691432189"
    # 作者主页
    author_url = "https://github.com/2691432189"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediasyncdelemt"
    # 加载顺序
    plugin_order = 9
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    _enabled = False
    _sync_type: str = ""
    _notify = False
    _del_source = False
    _del_history = False
    _exclude_path = None
    _library_path = None
    _transferchain = None
    _transferhis = None
    _downloadhis = None
    _default_downloader = None
    _storagechain = None

    def init_plugin(self, config: dict = None):
        self._transferchain = TransferChain()
        self._downloader_helper = DownloaderHelper()
        self._transferhis = TransferHistoryOper()
        self._downloadhis = DownloadHistoryOper()
        self._storagechain = StorageChain()

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._sync_type = config.get("sync_type")
            self._notify = config.get("notify")
            self._del_source = config.get("del_source")
            self._del_history = config.get("del_history")
            self._exclude_path = config.get("exclude_path")
            self._library_path = config.get("library_path")

            # 获取默认下载器
            downloader_services = self._downloader_helper.get_services()
            for downloader_name, downloader_info in downloader_services.items():
                if downloader_info.config.default:
                    self._default_downloader = downloader_name

            # 清理插件历史
            if self._del_history:
                self.del_data(key="history")
                self.update_config({
                    "enabled": self._enabled,
                    "sync_type": self._sync_type,
                    "notify": self._notify,
                    "del_source": self._del_source,
                    "del_history": False,
                    "exclude_path": self._exclude_path,
                    "library_path": self._library_path
                })

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/delete_history",
                "endpoint": self.delete_history,
                "methods": ["GET"],
                "summary": "删除订阅历史记录"
            }
        ]

    def delete_history(self, key: str, apikey: str):
        """
        删除历史记录
        """
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API密钥错误")
        # 历史记录
        historys = self.get_data('history')
        if not historys:
            return schemas.Response(success=False, message="未找到历史记录")
        # 删除指定记录
        historys = [h for h in historys if h.get("unique") != key]
        self.save_data('history', historys)
        return schemas.Response(success=True, message="删除成功")

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
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
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
                                    'md': 3
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
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'del_source',
                                            'label': '删除源文件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'del_history',
                                            'label': '删除历史',
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
                                            'model': 'sync_type',
                                            'label': '媒体库同步方式',
                                            'items': [
                                                {'title': 'Webhook', 'value': 'webhook'},
                                                {'title': 'Scripter X', 'value': 'plugin'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude_path',
                                            'label': '排除路径'
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
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'library_path',
                                            'rows': '2',
                                            'label': '媒体库路径映射',
                                            'placeholder': '媒体服务器路径:MoviePilot路径（一行一个）'
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
                                            'text': '媒体库同步方式分为Webhook、Scripter X：'
                                                    '1、Webhook需要Emby4.8.0.45及以上开启媒体删除的Webhook。'
                                                    '2、Scripter X方式需要emby安装并配置Scripter X插件，无需配置执行周期。'
                                                    '3、启用该插件后，非媒体服务器触发的源文件删除，也会同步处理下载器中的下载任务。'
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
                                            'text': '关于路径映射（转移后文件路径）：'
                                                    'emby:/data/A.mp4,'
                                                    'moviepilot:/mnt/link/A.mp4。'
                                                    '路径映射填/data:/mnt/link。'
                                                    '不正确配置会导致查询不到转移记录！（路径一样可不填）'
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
                                            'text': '排除路径：命中排除路径后请求云盘删除插件删除云盘资源。'
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
                                            'text': 'Scripter X配置文档：'
                                                    'https://github.com/thsrite/'
                                                    'MediaSyncDel/blob/main/MoviePilot/MoviePilot.md'
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
                                            'text': '路径映射配置文档：'
                                                    'https://github.com/thsrite/MediaSyncDel/blob/main/path.md'
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
            "notify": True,
            "del_source": False,
            "del_history": False,
            "library_path": "",
            "sync_type": "webhook",
            "exclude_path": "",
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询同步详情
        historys = self.get_data('history')
        if not historys:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        # 数据按时间降序排序
        historys = sorted(historys, key=lambda x: x.get('del_time'), reverse=True)
        # 拼装页面
        contents = []
        for history in historys:
            htype = history.get("type")
            title = history.get("title")
            unique = history.get("unique")
            year = history.get("year")
            season = history.get("season")
            episode = history.get("episode")
            image = history.get("image")
            del_time = history.get("del_time")

            if season:
                sub_contents = [
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'类型：{htype}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'标题：{title}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'年份：{year}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'季：{season}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'集：{episode}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'时间：{del_time}'
                    }
                ]
            else:
                sub_contents = [
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'类型：{htype}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'标题：{title}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'年份：{year}'
                    },
                    {
                        'component': 'VCardText',
                        'props': {
                            'class': 'pa-0 px-2'
                        },
                        'text': f'时间：{del_time}'
                    }
                ]

            contents.append(
                {
                    'component': 'VCard',
                    'content': [
                        {
                            "component": "VDialogCloseBtn",
                            "props": {
                                'innerClass': 'absolute top-0 right-0',
                            },
                            'events': {
                                'click': {
                                    'api': 'plugin/MediaSyncDel/delete_history',
                                    'method': 'get',
                                    'params': {
                                        'key': unique,
                                        'apikey': settings.API_TOKEN
                                    }
                                }
                            },
                        },
                        {
                            'component': 'div',
                            'props': {
                                'class': 'd-flex justify-space-start flex-nowrap flex-row',
                            },
                            'content': [
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VImg',
                                            'props': {
                                                'src': image,
                                                'height': 120,
                                                'width': 80,
                                                'aspect-ratio': '2/3',
                                                'class': 'object-cover shadow ring-gray-500',
                                                'cover': True
                                            }
                                        }
                                    ]
                                },
                                {
                                    'component': 'div',
                                    'content': sub_contents
                                }
                            ]
                        }
                    ]
                }
            )

        return [
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-3 grid-info-card',
                },
                'content': contents
            }
        ]

    @eventmanager.register(EventType.WebhookMessage)
    def sync_del_by_webhook(self, event: Event):
        """
        emby删除媒体库同步删除历史记录
        webhook
        """
        if not self._enabled or str(self._sync_type) != "webhook":
            return

        event_data = event.event_data
        event_type = event_data.event

        # Emby Webhook event_type = library.deleted
        if not event_type or str(event_type) not in ['library.deleted', 'ItemDeleted']:
            return

        # 媒体类型
        media_type = event_data.media_type
        # 媒体名称
        media_name = event_data.item_name
        # 媒体路径
        media_path = event_data.item_path
        # tmdb_id
        tmdb_id = event_data.tmdb_id
        # 季数
        season_num = event_data.season_id
        # 集数
        episode_num = event_data.episode_id

        """
        执行删除逻辑
        """
        if self._exclude_path and media_path and any(
                os.path.abspath(media_path).startswith(os.path.abspath(path)) for path in
                self._exclude_path.split(",")):
            logger.info(f"媒体路径 {media_path} 已被排除，暂不处理")
            return

        # 兼容emby webhook season删除没有发送tmdbid
        if not tmdb_id and str(media_type) != 'Season':
            logger.error(f"{media_name} 同步删除失败，未获取到TMDB ID，请检查媒体库媒体是否刮削")
            return

        self.__sync_del(media_type=media_type,
                        media_name=media_name,
                        media_path=media_path,
                        tmdb_id=tmdb_id,
                        season_num=season_num,
                        episode_num=episode_num)

    @eventmanager.register(EventType.WebhookMessage)
    def sync_del_by_plugin(self, event):
        """
        emby删除媒体库同步删除历史记录
        Scripter X插件
        """
        if not self._enabled or str(self._sync_type) != "plugin":
            return

        event_data = event.event_data
        event_type = event_data.event

        # Scripter X插件 event_type = media_del
        if not event_type or str(event_type) != 'media_del':
            return

        # Scripter X插件 需要是否虚拟标识
        item_isvirtual = event_data.item_isvirtual
        if not item_isvirtual:
            logger.error("Scripter X插件方式，item_isvirtual参数未配置，为防止误删除，暂停插件运行")
            self.update_config({
                "enabled": False,
                "del_source": self._del_source,
                "exclude_path": self._exclude_path,
                "library_path": self._library_path,
                "notify": self._notify,
                "sync_type": self._sync_type,
            })
            return

        # 如果是虚拟item，则直接return，不进行删除
        if item_isvirtual == 'True':
            return

        # 媒体类型
        media_type = event_data.item_type
        # 媒体名称
        media_name = event_data.item_name
        # 媒体路径
        media_path = event_data.item_path
        # tmdb_id
        tmdb_id = event_data.tmdb_id
        # 季数
        season_num = event_data.season_id
        # 集数
        episode_num = event_data.episode_id

        """
        执行删除逻辑
        """
        if self._exclude_path and media_path and any(
                os.path.abspath(media_path).startswith(os.path.abspath(path)) for path in
                self._exclude_path.split(",")):
            logger.info(f"媒体路径 {media_path} 已被排除，暂不处理")
            # 发送消息通知网盘删除插件删除网盘资源
            return

        if not tmdb_id or not str(tmdb_id).isdigit():
            logger.error(f"{media_name} 同步删除失败，未获取到TMDB ID，请检查媒体库媒体是否刮削")
            return

        self.__sync_del(media_type=media_type,
                        media_name=media_name,
                        media_path=media_path,
                        tmdb_id=tmdb_id,
                        season_num=season_num,
                        episode_num=episode_num)

    def __sync_del(self, media_type: str, media_name: str, media_path: str,
                   tmdb_id: int, season_num: str, episode_num: str):
        if not media_type:
            logger.error(f"{media_name} 同步删除失败，未获取到媒体类型，请检查媒体是否刮削")
            return

        # 处理路径映射 (处理同一媒体多分辨率的情况)
        if self._library_path:
            paths = self._library_path.split("\n")
            for path in paths:
                sub_paths = path.split(":")
                if len(sub_paths) < 2:
                    continue
                media_path = media_path.replace(sub_paths[0], sub_paths[1]).replace('\\', '/')

        # 兼容重新整理的场景
        if Path(media_path).exists():
            logger.warn(f"转移路径 {media_path} 未被删除或重新生成，跳过处理")
            return

        # 查询转移记录
        msg, transfer_history = self.__get_transfer_his(media_type=media_type,
                                                        media_name=media_name,
                                                        media_path=media_path,
                                                        tmdb_id=tmdb_id,
                                                        season_num=season_num,
                                                        episode_num=episode_num)

        logger.info(f"正在同步删除{msg}")

        if not transfer_history:
            logger.warn(
                f"{media_type} {media_name} 未获取到可删除数据，请检查路径映射是否配置错误，请检查tmdbid获取是否正确")
            return

        logger.info(f"获取到 {len(transfer_history)} 条转移记录，开始同步删除")
        # 开始删除
        year = None
        del_torrent_hashs = []
        stop_torrent_hashs = []
        error_cnt = 0
        image = 'https://emby.media/notificationicon.png'
        for transferhis in transfer_history:
            title = transferhis.title
            if title not in media_name:
                logger.warn(
                    f"当前转移记录 {transferhis.id} {title} {transferhis.tmdbid} 与删除媒体{media_name}不符，防误删，暂不自动删除")
                continue
            image = transferhis.image or image
            year = transferhis.year

            # 0、删除转移记录
            self._transferhis.delete(transferhis.id)

            # 删除种子任务
            if self._del_source:
                # 1、直接删除源文件
                if transferhis.src and Path(transferhis.src).suffix in settings.RMT_MEDIAEXT:
                    # 删除硬链接文件和源文件
                    if Path(transferhis.dest).exists():
                        Path(transferhis.dest).unlink(missing_ok=True)
                        self.__remove_parent_dir(Path(transferhis.dest))
                    if Path(transferhis.src).exists():
                        logger.info(f"源文件 {transferhis.src} 开始删除")
                        Path(transferhis.src).unlink(missing_ok=True)
                        logger.info(f"源文件 {transferhis.src} 已删除")
                        self.__remove_parent_dir(Path(transferhis.src))
                        if transferhis.download_hash:
                            logger.info(f"通知下载器助手删除文件,src: {transferhis.src},download_hash: {transferhis.download_hash}")
                            self.eventmanager.send_event(
                                EventType.DownloadFileDeleted,
                                {
                                    "src": transferhis.src,
                                    "hash": transferhis.download_hash
                                }
                            )

        logger.info(f"同步删除 {msg} 完成！")

        media_type = MediaType.MOVIE if media_type in ["Movie", "MOV"] else MediaType.TV

        # 发送消息
        if self._notify:
            backrop_image = self.chain.obtain_specific_image(
                mediaid=tmdb_id,
                mtype=media_type,
                image_type=MediaImageType.Backdrop,
                season=season_num,
                episode=episode_num
            ) or image

            torrent_cnt_msg = ""
            if del_torrent_hashs:
                torrent_cnt_msg += f"删除种子{len(set(del_torrent_hashs))}个\n"
            if stop_torrent_hashs:
                stop_cnt = 0
                # 排除已删除
                for stop_hash in set(stop_torrent_hashs):
                    if stop_hash not in set(del_torrent_hashs):
                        stop_cnt += 1
                if stop_cnt > 0:
                    torrent_cnt_msg += f"暂停种子{stop_cnt}个\n"
            if error_cnt:
                torrent_cnt_msg += f"删种失败{error_cnt}个\n"
            # 发送通知
            self.post_message(
                mtype=NotificationType.Plugin,
                title="媒体库同步删除任务完成",
                image=backrop_image,
                text=f"{msg}\n"
                     f"删除记录{len(transfer_history)}个\n"
                     f"{torrent_cnt_msg}"
                     f"时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
            )

        # 读取历史记录
        history = self.get_data('history') or []

        # 获取poster
        poster_image = self.chain.obtain_specific_image(
            mediaid=tmdb_id,
            mtype=media_type,
            image_type=MediaImageType.Poster,
        ) or image
        history.append({
            "type": media_type.value,
            "title": media_name,
            "year": year,
            "path": media_path,
            "season": season_num if season_num and str(season_num).isdigit() else None,
            "episode": episode_num if episode_num and str(episode_num).isdigit() else None,
            "image": poster_image,
            "del_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
            "unique": f"{media_name}:{tmdb_id}:{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}"
        })

        # 保存历史
        self.save_data("history", history)

    def __remove_parent_dir(self, file_path: Path):
        """
        删除父目录
        """
        # 删除空目录
        # 判断当前媒体父路径下是否有媒体文件，如有则无需遍历父级
        if not SystemUtils.exits_files(file_path.parent, settings.RMT_MEDIAEXT):
            # 判断父目录是否为空, 为空则删除
            i = 0
            for parent_path in file_path.parents:
                i += 1
                if i > 3:
                    break
                if str(parent_path.parent) != str(file_path.root):
                    # 父目录非根目录，才删除父目录
                    if not SystemUtils.exits_files(parent_path, settings.RMT_MEDIAEXT):
                        # 当前路径下没有媒体文件则删除
                        shutil.rmtree(parent_path)
                        logger.warn(f"本地空目录 {parent_path} 已删除")

    def __get_transfer_his(self, media_type: str, media_name: str, media_path: str,
                           tmdb_id: int, season_num: str, episode_num: str):
        """
        查询转移记录
        """
        # 季数
        if season_num and str(season_num).isdigit():
            season_num = str(season_num).rjust(2, '0')
        else:
            season_num = None
        # 集数
        if episode_num and str(episode_num).isdigit():
            episode_num = str(episode_num).rjust(2, '0')
        else:
            episode_num = None

        # 类型
        mtype = MediaType.MOVIE if media_type in ["Movie", "MOV"] else MediaType.TV

        # 删除电影
        if mtype == MediaType.MOVIE:
            msg = f'电影 {media_name} {tmdb_id}'
            transfer_history: List[TransferHistory] = self._transferhis.get_by(tmdbid=tmdb_id,
                                                                               mtype=mtype.value,
                                                                               dest=media_path)
        # 删除电视剧
        elif mtype == MediaType.TV and not season_num and not episode_num:
            msg = f'剧集 {media_name} {tmdb_id}'
            transfer_history: List[TransferHistory] = self._transferhis.get_by(tmdbid=tmdb_id,
                                                                               mtype=mtype.value)
        # 删除季 S02
        elif mtype == MediaType.TV and season_num and not episode_num:
            if not season_num or not str(season_num).isdigit():
                logger.error(f"{media_name} 季同步删除失败，未获取到具体季")
                return
            msg = f'剧集 {media_name} S{season_num} {tmdb_id}'
            if tmdb_id and str(tmdb_id).isdigit():
                # 根据tmdb_id查询转移记录
                transfer_history: List[TransferHistory] = self._transferhis.get_by(tmdbid=tmdb_id,
                                                                                   mtype=mtype.value,
                                                                                   season=f'S{season_num}')
            else:
                # 兼容emby webhook不发送tmdb场景
                transfer_history: List[TransferHistory] = self._transferhis.get_by(mtype=mtype.value,
                                                                                   season=f'S{season_num}',
                                                                                   dest=media_path)
        # 删除剧集S02E02
        elif mtype == MediaType.TV and season_num and episode_num:
            if not season_num or not str(season_num).isdigit() or not episode_num or not str(episode_num).isdigit():
                logger.error(f"{media_name} 集同步删除失败，未获取到具体集")
                return
            msg = f'剧集 {media_name} S{season_num}E{episode_num} {tmdb_id}'
            transfer_history: List[TransferHistory] = self._transferhis.get_by(tmdbid=tmdb_id,
                                                                               mtype=mtype.value,
                                                                               season=f'S{season_num}',
                                                                               episode=f'E{episode_num}',
                                                                               dest=media_path)
        else:
            return "", []

        return msg, transfer_history

    def get_state(self):
        return self._enabled

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    @staticmethod
    def get_tmdbimage_url(path: str, prefix="w500"):
        if not path:
            return ""
        tmdb_image_url = f"https://{settings.TMDB_IMAGE_DOMAIN}"
        return tmdb_image_url + f"/t/p/{prefix}{path}"
