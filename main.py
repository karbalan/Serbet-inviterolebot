import sys
from modubot import Bot
import asyncio

def main():
    #bot: Bot = Bot()
    bot = Bot()
    bot.run()

if __name__ == "__main__":
    asyncio.run(main())
    #main()
    