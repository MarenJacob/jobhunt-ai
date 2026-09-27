import base64, hashlib, hmac, json, secrets, time

def issue_token(profile: dict, secret: str, ttl_seconds=900):
    payload={'v':1,'iat':int(time.time()),'exp':int(time.time())+ttl_seconds,'nonce':secrets.token_urlsafe(12),'candidate':profile}
    body=base64.urlsafe_b64encode(json.dumps(payload,separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new(secret.encode(),body.encode(),hashlib.sha256).hexdigest()
    return {'token':body+'.'+sig,'expires_at':payload['exp'],'protocol':'candidate-career-token-v1'}

def verify_token(token: str, secret: str):
    try:
        body,sig=token.rsplit('.',1)
        expected=hmac.new(secret.encode(),body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected): return None
        padded=body+'='*(-len(body)%4); payload=json.loads(base64.urlsafe_b64decode(padded))
        if payload['exp']<int(time.time()): return None
        return payload
    except Exception: return None
