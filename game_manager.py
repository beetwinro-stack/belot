"""
GameManager: manages all active Belot games.
"""
import uuid
from game import BelotGame, GameState


class GameManager:
    def __init__(self):
        self.games = {}           # game_id -> BelotGame
        self.player_to_game = {}  # player_id -> game_id

    def create_game(self, creator_id: int, creator_name: str) -> BelotGame:
        game_id = str(uuid.uuid4())[:8].upper()
        game = BelotGame(game_id)
        game.add_player(creator_id, creator_name)
        self.games[game_id] = game
        self.player_to_game[creator_id] = game_id
        return game

    def join_game(self, game_id: str, player_id: int, player_name: str) -> tuple:
        """Returns (game, error_message)."""
        game = self.games.get(game_id)
        if not game:
            return None, "Игра не найдена. Проверьте код игры."
        if game.state != GameState.WAITING:
            return None, "Игра уже началась."
        if player_id in game.players:
            return None, "Вы уже в этой игре."
        if game.is_full():
            return None, "Игра заполнена (4/4 игроков)."

        if player_id in self.player_to_game:
            old_gid = self.player_to_game[player_id]
            old_game = self.games.get(old_gid)
            if old_game and old_game.state == GameState.WAITING:
                old_game.players.remove(player_id)
                if not old_game.players:
                    del self.games[old_gid]

        game.add_player(player_id, player_name)
        self.player_to_game[player_id] = game_id

        if game.is_full():
            game.start_round()

        return game, None

    def get_game_by_player(self, player_id: int):
        gid = self.player_to_game.get(player_id)
        return self.games.get(gid) if gid else None

    def get_game(self, game_id: str):
        return self.games.get(game_id)

    def remove_game(self, game_id: str):
        game = self.games.pop(game_id, None)
        if game:
            for pid in game.players:
                self.player_to_game.pop(pid, None)
