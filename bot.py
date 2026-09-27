import asyncio
import logging
import os
import random
import time
from typing import Optional

import discord_ios

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
VOICE_CHANNEL_ID = int(os.environ["VOICE_CHANNEL_ID"])
CUSTOM_EMOJI_NAME_GNORP = os.environ["CUSTOM_EMOJI_NAME_GNORP"]
CUSTOM_EMOJI_ID_GNORP = os.environ["CUSTOM_EMOJI_ID_GNORP"]
CUSTOM_EMOJI_ID_AUTISMO = os.environ["CUSTOM_EMOJI_ID_AUTISMO"]
CUSTOM_EMOJI_NAME_AUTISMO = os.environ["CUSTOM_EMOJI_NAME_AUTISMO"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logging.getLogger("discord").setLevel(logging.INFO)
logging.getLogger("discord.voice_state").setLevel(logging.ERROR)


intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
        )

        self.started_at = time.monotonic()
        self.voice_reconnect_task: Optional[asyncio.Task] = None
        self.voice_connect_lock = asyncio.Lock()

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)

        logging.info(
            "Registered commands: %s",
            ", ".join(command.name for command in synced),
        )

    async def on_ready(self):
        logging.info("Logged in as %s", self.user)

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="The Autismos! ♾️",
        )

        await self.change_presence(
            status=discord.Status.online,
            activity=activity,
        )

        logging.info(
            "Presence set: status=%s, activity=%s",
            discord.Status.online,
            activity,
        )

        if (
            self.voice_reconnect_task is None
            or self.voice_reconnect_task.done()
        ):
            logging.info("Starting voice connection loop")

            self.voice_reconnect_task = asyncio.create_task(
                self.voice_connection_loop(),
                name="voice-connection-loop",
            )
        else:
            logging.info("Voice connection loop already running")

    async def voice_connection_loop(self):
        while not self.is_closed():
            try:
                guild = self.get_guild(GUILD_ID)

                if guild is None:
                    logging.warning(
                        "Guild %s is not available yet; retrying in 5 seconds",
                        GUILD_ID,
                    )
                    await asyncio.sleep(5)
                    continue

                voice_client = guild.voice_client

                if voice_client is None:
                    logging.info(
                        "No voice client found; connecting to target channel"
                    )
                    await self.join_target_channel()

                elif not voice_client.is_connected():
                    logging.warning(
                        "Voice client is disconnected; reconnecting"
                    )

                    await voice_client.disconnect(force=True)
                    await asyncio.sleep(2)
                    await self.join_target_channel()

                await asyncio.sleep(30)

            except asyncio.CancelledError:
                logging.info("Voice connection loop cancelled")
                raise

            except Exception:
                logging.exception(
                    "Voice connection failed; retrying in 5 seconds"
                )
                await asyncio.sleep(5)

    async def join_target_channel(self):
        async with self.voice_connect_lock:
            guild = self.get_guild(GUILD_ID)

            if guild is None:
                raise RuntimeError(
                    f"Could not find guild {GUILD_ID}. "
                    "Make sure the bot is in the server."
                )

            channel = guild.get_channel(VOICE_CHANNEL_ID)

            if channel is None:
                channel = await self.fetch_channel(VOICE_CHANNEL_ID)

            if not isinstance(channel, discord.VoiceChannel):
                raise TypeError(
                    "VOICE_CHANNEL_ID is not a valid voice channel."
                )

            existing = guild.voice_client

            if existing is not None:
                if existing.is_connected():
                    if existing.channel.id == channel.id:
                        logging.info(
                            "Already connected to voice channel: %s",
                            channel.name,
                        )
                        return existing

                    logging.info(
                        "Moving from voice channel %s to %s",
                        existing.channel.name,
                        channel.name,
                    )

                    await existing.move_to(channel)
                    return existing

                logging.info(
                    "Removing stale voice client before reconnecting"
                )

                await existing.disconnect(force=True)
                await asyncio.sleep(2)

            logging.info(
                "Calling channel.connect(): guild=%s channel=%s",
                guild.id,
                channel.id,
            )

            voice_client = await channel.connect(
                self_deaf=True,
                self_mute=True,
                reconnect=True,
            )

            logging.info(
                "Connected to voice channel: %s",
                channel.name,
            )

            return voice_client


bot = Bot()

class ConnectFour(discord.ui.View):
    def __init__(self, player1, player2=None):
        super().__init__(timeout=300)

        self.player1 = player1
        self.player2 = player2
        self.bot_mode = player2 is None
        self.current_player = player1

        self.board = [
            ["⚫" for _ in range(7)]
            for _ in range(6)
        ]

        for column in range(7):
            button = discord.ui.Button(
                label=str(column + 1),
                style=discord.ButtonStyle.primary,
                row=0 if column < 5 else 1
            )

            async def callback(
                interaction: discord.Interaction,
                column=column
            ):
                await self.play_column(interaction, column)

            button.callback = callback
            self.add_item(button)

    def available_columns(self):
        return [
            column
            for column in range(7)
            if self.board[0][column] == "⚫"
        ]

    def drop_piece(self, column, piece):
        for row in range(5, -1, -1):
            if self.board[row][column] == "⚫":
                self.board[row][column] = piece
                return row

        return None

    def has_won(self, row, column, piece):
        directions = [
            (0, 1),
            (1, 0),
            (1, 1),
            (1, -1),
        ]

        for row_change, column_change in directions:
            total = 1

            for direction in (1, -1):
                r = row + row_change * direction
                c = column + column_change * direction

                while (
                    0 <= r < 6
                    and 0 <= c < 7
                    and self.board[r][c] == piece
                ):
                    total += 1
                    r += row_change * direction
                    c += column_change * direction

            if total >= 4:
                return True

        return False

    def is_draw(self):
        return not self.available_columns()

    async def interaction_check(self, interaction):
        players = {self.player1.id}

        if self.player2 is not None:
            players.add(self.player2.id)

        if interaction.user.id not in players:
            await interaction.response.send_message(
                "You are not playing this game.",
                ephemeral=True
            )
            return False

        return True

    async def play_column(self, interaction, column):
        if self.bot_mode:
            if interaction.user.id != self.player1.id:
                await interaction.response.send_message(
                    "You are not playing this game.",
                    ephemeral=True
                )
                return

            if self.current_player != self.player1:
                await interaction.response.send_message(
                    "Wait for the bot to move.",
                    ephemeral=True
                )
                return

        else:
            if interaction.user.id != self.current_player.id:
                await interaction.response.send_message(
                    "It is not your turn.",
                    ephemeral=True
                )
                return

        piece = (
            "🔴"
            if self.current_player == self.player1
            else "🟡"
        )

        row = self.drop_piece(column, piece)

        if row is None:
            await interaction.response.send_message(
                "That column is full.",
                ephemeral=True
            )
            return

        if self.has_won(row, column, piece):
            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(
                content=(
                    f"**{interaction.user.display_name} wins!**\n\n"
                    f"{self.board_text()}"
                ),
                view=self
            )
            return

        if self.is_draw():
            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(
                content=f"**Draw!**\n\n{self.board_text()}",
                view=self
            )
            return

        if self.bot_mode:
            self.current_player = "BOT"

            await interaction.response.edit_message(
                content=(
                    f"Waiting for the bot...\n\n"
                    f"{self.board_text()}"
                ),
                view=self
            )

            await self.bot_move(interaction.message)
            return

        self.current_player = (
            self.player2
            if self.current_player == self.player1
            else self.player1
        )

        await interaction.response.edit_message(
            content=(
                f"{self.current_player.mention}'s turn.\n\n"
                f"{self.board_text()}"
            ),
            view=self
        )

    async def bot_move(self, message):
        import random

        columns = self.available_columns()
        column = random.choice(columns)

        row = self.drop_piece(column, "🟡")

        if self.has_won(row, column, "🟡"):
            for item in self.children:
                item.disabled = True

            await message.edit(
                content=f"**The bot wins!**\n\n{self.board_text()}",
                view=self
            )
            return

        if self.is_draw():
            for item in self.children:
                item.disabled = True

            await message.edit(
                content=f"**Draw!**\n\n{self.board_text()}",
                view=self
            )
            return

        self.current_player = self.player1

        await message.edit(
            content=(
                f"Your turn, {self.player1.mention}.\n\n"
                f"{self.board_text()}"
            ),
            view=self
        )

    def board_text(self):
        header = "  1  2  3  4  5  6  7"
        rows = "\n".join(" ".join(row) for row in self.board)
        return f"{header}\n{rows}"


def check_winner(board: list[Optional[str]]) -> Optional[str]:
    winning_lines = [
        (0, 1, 2),
        (3, 4, 5),
        (6, 7, 8),
        (0, 3, 6),
        (1, 4, 7),
        (2, 5, 8),
        (0, 4, 8),
        (2, 4, 6),
    ]

    for a, b, c in winning_lines:
        if (
            board[a]
            and board[a] == board[b]
            and board[a] == board[c]
        ):
            return board[a]

    if all(board):
        return "draw"

    return None


def get_bot_move(board: list[Optional[str]]) -> Optional[int]:
    empty_spaces = [
        index
        for index, value in enumerate(board)
        if value is None
    ]

    if not empty_spaces:
        return None

    if board[4] is None:
        return 4

    return random.choice(empty_spaces)


def format_uptime(seconds: float) -> str:
    total_seconds = int(seconds)

    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    parts.append(f"{seconds}s")

    return " ".join(parts)


class TicTacToeView(discord.ui.View):
    def __init__(
        self,
        *,
        board: list[Optional[str]],
        player_x: discord.User,
        player_o: Optional[discord.User],
        is_bot_game: bool,
        current_turn: int | str,
    ):
        super().__init__(timeout=120)

        self.board = board
        self.player_x = player_x
        self.player_o = player_o
        self.is_bot_game = is_bot_game
        self.current_turn = current_turn
        self.message: Optional[discord.Message] = None
        self.game_over = False

        self.create_buttons()

    def create_buttons(self):
        for index, value in enumerate(self.board):
            if value == "X":
                style = discord.ButtonStyle.danger
            elif value == "O":
                style = discord.ButtonStyle.success
            else:
                style = discord.ButtonStyle.secondary

            button = discord.ui.Button(
                label=value or "·",
                style=style,
                custom_id=f"ttt_{index}",
                disabled=self.game_over or value is not None,
                row=index // 3,
            )

            button.callback = self.make_button_callback(index)
            self.add_item(button)

    def refresh_buttons(self):
        for index, item in enumerate(self.children):
            if not isinstance(item, discord.ui.Button):
                continue

            value = self.board[index]

            item.label = value or "·"
            item.disabled = self.game_over or value is not None

            if value == "X":
                item.style = discord.ButtonStyle.danger
            elif value == "O":
                item.style = discord.ButtonStyle.success
            else:
                item.style = discord.ButtonStyle.secondary

    def make_button_callback(self, position: int):
        async def callback(interaction: discord.Interaction):
            await self.handle_move(interaction, position)

        return callback

    def game_content(self, result: Optional[str] = None) -> str:
        if result == "X":
            return f"{self.player_x.mention} wins! 🎉"

        if result == "O":
            if self.is_bot_game:
                return "I win! 🤖"

            return f"{self.player_o.mention} wins! 🎉"

        if result == "draw":
            return "It's a draw!"

        if self.current_turn == self.player_x.id:
            current_player = self.player_x.mention
        elif self.is_bot_game and self.current_turn == "bot":
            current_player = "the bot"
        else:
            current_player = self.player_o.mention

        player_o_text = (
            "the bot is **O**"
            if self.is_bot_game
            else f"{self.player_o.mention} is **O**"
        )

        return (
            f"{self.player_x.mention} is **X** and "
            f"{player_o_text}.\n"
            f"It is {current_player}'s turn."
        )

    async def handle_move(
        self,
        interaction: discord.Interaction,
        position: int,
    ):
        user_id = interaction.user.id

        is_current_human_player = (
            self.current_turn != "bot"
            and user_id == self.current_turn
            and (
                user_id == self.player_x.id
                or (
                    self.player_o is not None
                    and user_id == self.player_o.id
                )
            )
        )

        if not is_current_human_player:
            await interaction.response.send_message(
                "It is not your turn.",
                ephemeral=True,
            )
            return

        if position < 0 or position > 8 or self.board[position]:
            await interaction.response.send_message(
                "That square is already taken.",
                ephemeral=True,
            )
            return

        mark = "X" if user_id == self.player_x.id else "O"
        self.board[position] = mark

        result = check_winner(self.board)

        if result:
            self.game_over = True
            self.stop()
            self.disable_all_items()
            self.refresh_buttons()

            await interaction.response.edit_message(
                content=self.game_content(result),
                view=self,
            )
            return

        if self.current_turn == self.player_x.id:
            self.current_turn = (
                "bot"
                if self.is_bot_game
                else self.player_o.id
            )
        else:
            self.current_turn = self.player_x.id

        if self.is_bot_game and self.current_turn == "bot":
            bot_move = get_bot_move(self.board)

            if bot_move is not None:
                self.board[bot_move] = "O"

            result = check_winner(self.board)

            if result:
                self.game_over = True
                self.stop()
                self.disable_all_items()
                self.refresh_buttons()

                await interaction.response.edit_message(
                    content=self.game_content(result),
                    view=self,
                )
                return

            self.current_turn = self.player_x.id

        self.refresh_buttons()

        await interaction.response.edit_message(
            content=self.game_content(),
            view=self,
        )

    def disable_all_items(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self.game_over = True
        self.disable_all_items()
        self.refresh_buttons()

        if self.message is not None:
            try:
                await self.message.edit(
                    content="The game timed out.",
                    view=self,
                )
            except discord.HTTPException:
                pass


@bot.tree.command(
    name="help",
    description="Look at what I can do!",
)
async def help_command(interaction: discord.Interaction):
    commands_list = sorted(
        bot.tree.get_commands(),
        key=lambda command: command.name,
    )

    command_lines = [
        f"`/{command.name}` — {command.description}"
        for command in commands_list
    ]

    await interaction.response.send_message(
        "**I can do:**\n" + "\n".join(command_lines),
        ephemeral=False,
    )


@bot.tree.command(
    name="uptime",
    description="How long have I been autisming for? 🤔",
)
async def uptime(interaction: discord.Interaction):
    uptime_seconds = time.monotonic() - bot.started_at
    uptime_text = format_uptime(uptime_seconds)

    await interaction.response.send_message(
        f"I have been autisming for **{uptime_text}**."
    )


@bot.tree.command(
    name="gnorp",
    description="gives a gnorpcat!",
)
async def gnorp(interaction: discord.Interaction):
    emoji = f"<:{CUSTOM_EMOJI_NAME_GNORP}:{CUSTOM_EMOJI_ID_GNORP}>"
    await interaction.response.send_message(emoji)


@bot.tree.command(
    name="why",
    description="why the fuck not lol",
)
async def why(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Just for fun really. Some ppl here used to try and stay "
        "in vc as long as possible but that died out, so I wanna "
        "revive it. I run this on a VPS to ensure max uptime. "
        "There's a few basic commands too because I had a bit of "
        "fun lol, enjoy! 🩵"
    )


@bot.tree.command(
    name="tictactoe",
    description="play against me or someone else! I suck but ill try.",
)
@app_commands.describe(
    opponent="The player you want to challenge.",
)
async def tictactoe(
    interaction: discord.Interaction,
    opponent: Optional[discord.User] = None,
):
    player_x = interaction.user

    if opponent is not None and opponent.id == player_x.id:
        await interaction.response.send_message(
            "You cannot challenge yourself.",
            ephemeral=True,
        )
        return

    if opponent is not None and opponent.bot:
        await interaction.response.send_message(
            "You cannot challenge a bot. "
            "Leave the opponent empty to play against me.",
            ephemeral=True,
        )
        return

    board: list[Optional[str]] = [None] * 9
    is_bot_game = opponent is None

    view = TicTacToeView(
        board=board,
        player_x=player_x,
        player_o=opponent,
        is_bot_game=is_bot_game,
        current_turn=player_x.id,
    )

    await interaction.response.send_message(
        content=view.game_content(),
        view=view,
    )

    view.message = await interaction.original_response()


@bot.tree.command(
    name="autismo",
    description="an autismo, just for you 🩵♾️",
)
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"{interaction.user.mention} here's an autismo! "
        f"<:{CUSTOM_EMOJI_NAME_AUTISMO}:{CUSTOM_EMOJI_ID_AUTISMO}>"
    )

@bot.tree.command(
    name="teddy",
    description="teddy bears! 🧸❤️",
)
@app_commands.describe(
    person="Who do you want to give a bear to?",
)
async def teddy(
    interaction: discord.Interaction,
    person: discord.Member,
):
    await interaction.response.send_message(
        f"{interaction.user.mention} gives a teddy bear to {person.mention} 🧸❤️"
    )

@bot.tree.command(
    name="connect4",
    description="Play Connect 4 against me or another person, again, I suck but ill try."
)
@app_commands.describe(
    opponent="Leave empty to play against me"
)
async def connect4(
    interaction: discord.Interaction,
    opponent: discord.Member = None
):
    if opponent is not None:
        if opponent.bot:
            await interaction.response.send_message(
                "You cannot play against another bot.",
                ephemeral=True
            )
            return

        if opponent.id == interaction.user.id:
            await interaction.response.send_message(
                "You cannot play against yourself.",
                ephemeral=True
            )
            return

    game = ConnectFour(
        player1=interaction.user,
        player2=opponent
    )

    if opponent is None:
        text = (
            f"{interaction.user.mention} vs **the bot**\n"
            f"{interaction.user.mention}'s turn.\n\n"
            f"{game.board_text()}"
        )
    else:
        text = (
            f"{interaction.user.mention} vs {opponent.mention}\n"
            f"{interaction.user.mention}'s turn.\n\n"
            f"{game.board_text()}"
        )

    await interaction.response.send_message(
        content=text,
        view=game
    )


bot.run(DISCORD_TOKEN)

