"""Bearer-only identity. No user IDs or roles trusted from request data."""
import hmac
import os
from urllib.parse import urlparse
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException


class Authenticator:
    def __init__(self,repo,mode=None,token=None,subject=None,issuer=None,audience=None,jwks_url=None):
        self.repo=repo
        self.mode=mode or os.getenv("AUTH_MODE","disabled")
        self.token=token or os.getenv("LOCAL_DEMO_TOKEN","")
        self.subject=subject or os.getenv("LOCAL_DEMO_SUBJECT","demo")
        self.issuer=issuer or os.getenv("OIDC_ISSUER","")
        self.audience=audience or os.getenv("OIDC_AUDIENCE","")
        self.jwks_url=jwks_url or os.getenv("OIDC_JWKS_URL","")
        self.jwks=None
        if self.mode=="oidc":
            if not self.issuer or not self.audience or urlparse(self.jwks_url).scheme!="https":
                raise RuntimeError("OIDC requires issuer, audience and configured HTTPS JWKS URL")
            self.jwks=PyJWKClient(self.jwks_url,timeout=5)
        elif self.mode=="local" and len(self.token)<32:
            raise RuntimeError("local demo token must contain at least 32 characters")
        elif self.mode not in ("local","disabled"):
            raise RuntimeError("unknown AUTH_MODE")

    def authenticate(self,authorization):
        unauthorized=HTTPException(401,"Authentication required",headers={"WWW-Authenticate":"Bearer"})
        if not authorization or not authorization.startswith("Bearer ") or len(authorization)>8192:
            raise unauthorized
        token=authorization[7:]
        if self.mode=="local":
            if not hmac.compare_digest(token.encode(),self.token.encode()):raise unauthorized
            issuer,subject="swarmforge-local",self.subject
        elif self.mode=="oidc":
            try:
                key=self.jwks.get_signing_key_from_jwt(token).key
                claims=jwt.decode(token,key,algorithms=["RS256"],issuer=self.issuer,audience=self.audience,options={"require":["exp","iss","aud","sub"]})
                issuer,subject=claims["iss"],claims["sub"]
                if not isinstance(subject,str) or not subject:raise ValueError()
            except (jwt.PyJWTError,ValueError,TypeError):raise unauthorized
        else:raise unauthorized
        p=self.repo.principal(issuer,subject)
        if not p:raise unauthorized
        return p
