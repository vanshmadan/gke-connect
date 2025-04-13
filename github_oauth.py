from quart import Blueprint, redirect, request, jsonify, session
import os, aiohttp
from urllib.parse import urlencode

github_bp = Blueprint("github", __name__)

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_CALLBACK_URL = os.getenv("GITHUB_CALLBACK_URL")  # http://localhost:5001/api/github/oauth/callback


@github_bp.route("/api/github/oauth/start")
async def github_oauth_start():
    env = request.args.get("env")
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_CALLBACK_URL + (f"?env={env}" if env else ""),
        "scope": "read:user repo",
        "allow_signup": "true",
        "prompt": "consent",  # 💡 Forces GitHub to re-prompt login screen
    }

    # Clear old token to ensure new account is prompted
    #session.pop("github_token", None)
    #session.pop("github_username", None)
 
    
    session.clear()

    return redirect(f"https://github.com/login/oauth/authorize?{urlencode(params)}")

@github_bp.route("/api/github/oauth/callback")
async def github_oauth_callback():
    code = request.args.get("code")
    env = request.args.get("env")
    async with aiohttp.ClientSession() as client:
        async with client.post("https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_CALLBACK_URL,
            }
        ) as res:
            data = await res.json()
            token = data.get("access_token")
            if not token:
                return jsonify({"error": "OAuth failed"}), 400
            session["github_token"] = token

        # ✅ Fetch user info
        async with client.get("https://api.github.com/user", headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }) as user_res:
            user_data = await user_res.json()
            session["github_username"] = user_data.get("login", "unknown")

    # ✅ Redirect back to correct env config page
    redirect_path = f"http://localhost:3000/environments/configuration/{env}" if env else "http://localhost:3000"
    return redirect(redirect_path)

@github_bp.route("/api/github/info")
async def github_info():
    token = session.get("github_token")
    username = session.get("github_username")
    if not token:
        return jsonify({"error": "Not authenticated"}), 403
    async with aiohttp.ClientSession() as client:
        async with client.get("https://api.github.com/user/repos",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }
        ) as res:
            repos = await res.json()
    return jsonify({"username": username, "repos": repos})
