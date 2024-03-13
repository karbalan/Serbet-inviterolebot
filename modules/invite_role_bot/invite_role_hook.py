from aiohttp.client_exceptions import ServerDisconnectedError
from discord import Forbidden,Game,Guild,Invite,Member,NotFound,Role,Status
from modubot import ModuleBase
from tqdm import tqdm
from typing import List,Dict,Optional,TYPE_CHECKING

if TYPE_CHECKING:
    from modubot import Bot
    from .persistence_layer import Module as PersistenceLayer
    from ..core.func_inject import Module as FuncInject

class Module(ModuleBase):
    def __init__(self,bot: 'Bot') -> None:
        self._bot: Bot = bot
        self._persistence_layer: PersistenceLayer
        self._ready_guilds: Dict[int,bool] = {}
    
    async def postinit(self) -> None:
        func_inject: FuncInject = self._bot.get_module("modules.core.func_inject")
        self._persistence_layer = self._bot.get_module("modules.invite_role_bot.persistence_layer")

        func_inject.inject(self.on_guild_join)
        func_inject.inject(self.on_guild_update)
        func_inject.inject(self.on_guild_role_update)
        func_inject.inject(self.on_invite_create)
        func_inject.inject(self.on_invite_delete)
        func_inject.inject(self.on_member_join)
        func_inject.inject(self.on_shard_connect)

    async def prepare_guild(self,guild: Guild) -> bool:
        if guild.id not in self._ready_guilds:
            self._ready_guilds[guild.id] = False
            await self._persistence_layer.update_invite_uses(guild)
            self._ready_guilds[guild.id] = True
            return False
        return self._ready_guilds[guild.id]

    async def on_guild_join(self,guild: Guild) -> None:
        await self.prepare_guild(guild)

    async def on_guild_update(self,before: Guild,after: Guild) -> None:
        try:
            before_vanity: Optional[Invite] = await before.vanity_invite()
            after_vanity: Optional[Invite] = await after.vanity_invite()
            if after_vanity and after_vanity != before_vanity and await self._persistence_layer.invite_exists(after_vanity.code):
                await self._persistence_layer.update_invite_uses(after)
        except Forbidden or NotFound:
            pass
    
    async def on_guild_role_update(self,before: Role,after: Role) -> None:  #Intended for updating invite uses when the bot initially receives permission
        if not before.guild.me.guild_permissions.manage_guild and after.guild.me.guild_permissions.manage_guild:
            await self._persistence_layer.update_invite_uses(after.guild)

    async def on_invite_create(self,invite: Invite) -> None:
        assert isinstance(invite.guild,Guild)
        await self._persistence_layer.cache_guild_invites_add(invite.guild,invite)

    async def on_invite_delete(self,invite: Invite) -> None:
        assert isinstance(invite.guild,Guild)
        await self._persistence_layer.cache_guild_invites_remove(invite.guild,invite)

    async def on_member_join(self,member: Member) -> None:
        if member.bot:
            return
        if not await self.prepare_guild(member.guild):
            return
        if not member.guild.me.guild_permissions.manage_guild or not member.guild.me.guild_permissions.manage_roles:
            return
        used_invites: List[Invite] = await self._persistence_layer.update_invite_uses(member.guild)
        if used_invites:
            assert len(used_invites) == 1, "Other invites used before join"
            used_invite: Invite = used_invites[0]
            active_roles: List[Role]
            active_roles,_ = await self._persistence_layer.get_invite_roles(member.guild,used_invite.code)
            try:
                await member.add_roles(*active_roles,reason=f"Invite-roles for {used_invite.code}")
            except NotFound:
                pass    #Member no longer belongs to the guild (possibly left while fetching and updating invites)
    
    async def on_shard_connect(self,shard_id: int) -> None:
        await self._bot.wait_until_ready()
        await self._bot.change_presence(status=Status.idle,activity=Game(name="Starting up..."),shard_id=shard_id)
        shard_guilds: List[Guild] = [guild for guild in self._bot.guilds if guild.shard_id == shard_id]
        for guild in tqdm(shard_guilds,desc=f"Caching Invites for Shard #{shard_id}",unit=" guilds"):
            if not guild.unavailable:
                try:
                    await self.prepare_guild(guild)
                except ServerDisconnectedError:
                    return
        await self._bot.change_presence(status=Status.online,activity=Game(name="building @incubatoruldeanimatie"),shard_id=shard_id)