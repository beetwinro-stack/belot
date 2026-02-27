"""
GameManager: manages all active Belot games.
"""
import uuid
from game import BelotGame, GameState


class GameManager:
    def __init__(self):
        self.games = {}
        self.player_to_game = {}

    def create_game(self, creator_id: int, creator_name: str, max_players: int = 4) -> BelotGame:
        game_id = str(uuid.uuid4())[:8].upper()
        game = BelotGame(game_id, max_players=max_players)
        game.creator_id = creator_id
        game.add_player(creator_id, creator_name)
        self.games[game_id] = game
        self.player_to_game[creator_id] = game_id
        return game

    def join_game(self, game_id: str, player_id: int, player_name: str) -> tuple:
        game = self.games.get(game_id)
        if not game:
            return None, "Игра не найдена. Проверьте код игры."
        if game.state != GameState.WAITING:
            return None, "Игра уже началась."
        if player_id in game.players:
            return None, "Вы уже в этой игре."
        if game.is_full():
            return None, f"Игра заполнена ({game.max_players}/{game.max_players} игроков)."

        # If player is in a DIFFERENT waiting game — remove them from it
        old_gid = self.player_to_game.get(player_id)
        if old_gid and old_gid != game_id:
            old_game = self.games.get(old_gid)
            if old_game and old_game.state == GameState.WAITING:
                if player_id in old_game.players:
                    old_game.players.remove(player_id)
                old_game.player_names.pop(player_id, None)
                # Only delete old game if it's now completely empty
                if not old_game.players:
                    del self.games[old_gid]

        game.add_player(player_id, player_name)
        self.player_to_game[player_id] = game_id

        if game.is_full():
            game.start_round()

        return game, None

    def leave_game(self, player_id: int) -> dict:
        """
        Player leaves a waiting-room game.
        Returns { ok, was_creator, closed, game_id, remaining_players, player_name }
        """
        gid = self.player_to_game.get(player_id)
        if not gid:
            return {"ok": False, "error": "Вы не в игре."}

        game = self.games.get(gid)
        if not game:
            self.player_to_game.pop(player_id, None)
            return {"ok": False, "error": "Игра не найдена."}

        if game.state != GameState.WAITING:
            return {"ok": False, "error": "Нельзя выйти из уже начавшейся игры."}

        player_name = game.player_names.get(player_id, "?")
        was_creator = (getattr(game, "creator_id", None) == player_id)

        # Remove the player
        if player_id in game.players:
            game.players.remove(player_id)
        game.player_names.pop(player_id, None)
        self.player_to_game.pop(player_id, None)

        remaining = list(game.players)

        # Creator leaving → close table for everyone
        if was_creator or not remaining:
            for pid in remaining:
                self.player_to_game.pop(pid, None)
            self.games.pop(gid, None)
            return {
                "ok": True,
                "was_creator": was_creator,
                "closed": True,
                "game_id": gid,
                "remaining_players": remaining,
                "player_name": player_name,
            }

        # Normal player leaving — table stays open
        return {
            "ok": True,
            "was_creator": False,
            "closed": False,
            "game_id": gid,
            "remaining_players": remaining,
            "player_name": player_name,
            "game": game,
        }

    def close_game(self, creator_id: int) -> dict:
        return self.leave_game(creator_id)

    def get_game_by_player(self, player_id: int):
        gid = self.player_to_game.get(player_id)
        return self.games.get(gid) if gid else None

    def get_game(self, game_id: str):
        return self.games.get(game_id)

    def remove_game(self, game_id: str):
        game = self.games.pop(game_id, None)
        if game:
            for pid in list(game.players):
                self.player_to_game.pop(pid, None)
