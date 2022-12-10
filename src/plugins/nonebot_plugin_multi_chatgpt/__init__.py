from nonebot import get_driver
from .config import Config
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.log import logger
from asyncChatGPT.asyncChatGPT import Chatbot
from nonebot import require
import time
import asyncio


scheduler = require("nonebot_plugin_apscheduler").scheduler
global_config = get_driver().config
config = Config.parse_obj(global_config)

# 获取token列表
chatgpt_session_tokens = config.chatgpt_session_token_list
chatgpt_email_list = config.chatgpt_email_list
chatgpt_passwd_list = config.chatgpt_passwd_list

# 如果只有session_token
if len(chatgpt_email_list) == len(chatgpt_passwd_list) and len(chatgpt_session_tokens) != 0:
    chatgpt_email_list = len(chatgpt_session_tokens) * ['']
    chatgpt_passwd_list = len(chatgpt_session_tokens) * ['']
assert (len(chatgpt_email_list) == len(chatgpt_passwd_list))

config_list = [{
    "session_token": token,
    "email": email,
    "password": passwd,
} for token, email, passwd in zip(chatgpt_session_tokens, chatgpt_email_list, chatgpt_passwd_list)]

# 初始化chatbot
chat_bot_list = [Chatbot(i) for i in config_list]

# 触发器
chatGPT = on_command("。", aliases={"."}, priority=10, block=True)

# 用户会话ID map
user_session = dict()
# 计数
user_lock = dict()
# 使用标记
index = 0
# 标记一句话结束
punctuations = ['。', '！', '？', '.', '!', '?']


def use_old_chatbot(session_id) -> bool:
    logger.info(
        f"{session_id in user_session} {session_id in user_session and time.time() < user_session[session_id]['timestamp'] + 60 * 20}")
    if session_id in user_session:
        # 如果在20分钟内再次发起对话则使用相同的会话ID
        if time.time() < user_session[session_id]['timestamp'] + 60 * 20:
            logger.debug("使用之前的")
            return True
    return False


async def get_chat_response(session_id, prompt):
    global index
    logger.debug(f"index: {index}")

    if use_old_chatbot(session_id):
        chatbot = chat_bot_list[user_session[session_id]['bot_index']]
        chatbot.conversation_id = user_session[session_id]['conversation_id']
        chatbot.parent_id = user_session[session_id]['parent_id']
    else:
        # 超时或者如果没有发起过对话则获取新的chatbot
        chatbot = chat_bot_list[index]
        chatbot.reset_chat()

    msg = ''
    try:
        # handle_cache(resp, session_id)

        user_cache = dict()
        # 记录用户的bot index

        # logger.error(f"{not use_old_chatbot()}")
        if not use_old_chatbot(session_id):
            logger.info("新用户")
            user_cache['bot_index'] = index
        else:
            user_cache['bot_index'] = user_session[session_id]['bot_index']

            logger.info("老用户")

        index = (index + 1) % max(len(chatgpt_session_tokens), len(chatgpt_email_list))

        resp = await chatbot.get_chat_response(prompt)

        user_cache['timestamp'] = time.time()
        user_cache['conversation_id'] = resp['conversation_id']
        user_cache['parent_id'] = resp['parent_id']
        user_session[session_id] = user_cache

        return resp['message']

        # TODO: 是否需要增加长消息的功能
        # while True:
        #     if msg == '':
        #         resp = chatbot.get_chat_response(prompt)
        #     else:
        #         # 不是第一次请求
        #         resp = chatbot.get_chat_response("继续")
        #     msg += resp['message']
        #     # 如果最后一个字符是结尾标点符号则退出
        #     if resp['message'][-1] in punctuations:
        #         handle_cache(resp, session_id)
        #         return msg
    except Exception as e:
        logger.error(e)
        return f"发生错误 {str(e)}"


@chatGPT.handle()
async def _(event: GroupMessageEvent, arg: Message = CommandArg()):
    session_id = event.get_session_id()
    msg = arg.extract_plain_text().strip()
    logger.debug(f"{session_id} {msg}")
    # logger.info(user_session)

    if session_id in user_lock and user_lock[session_id]:
        await chatGPT.send("消息太快啦～请稍后", at_sender=True)
    else:
        user_lock[session_id] = True
        resp = await get_chat_response(session_id, msg)
        await chatGPT.send(resp, at_sender=True)
        user_lock[session_id] = False


# 定时刷新seesion_token
@scheduler.scheduled_job("interval", minutes=10)
async def refresh_session():
    logger.debug("refresh chatGPT session")
    for chatbot in chat_bot_list:
        # await chatbot.refresh_session()
        logger.debug(f"refresh chatGPT {chat_bot_list.index(chatbot)}")
        await asyncio.get_event_loop().run_in_executor(None, chatbot.refresh_session);


scheduler.add_job(refresh_session)