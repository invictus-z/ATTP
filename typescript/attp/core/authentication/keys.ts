/**
 * 密钥管理 — KeyStore 用于缓存公钥/私钥。
 *
 * 从 python/attp/core/authentication/keys.py 翻译而来。
 * 浏览器端使用 CryptoKey 对象替代 Python cryptography 库的密钥对象。
 */

/**
 * 密钥存储：管理公钥缓存 (nodeDid → publicKey) 和私钥缓存 (path → privateKey)。
 *
 * 在浏览器环境中，私钥通过 CryptoKey 对象表示，
 * 公钥同样为 CryptoKey 对象。
 */
export class KeyStore {
  private _cache: Map<string, CryptoKey> = new Map();
  private _privateKeyCache: Map<string, CryptoKey> = new Map();

  /**
   * 注入公钥到缓存。
   */
  cachePublicKey(nodeDid: string, publicKey: CryptoKey): void {
    this._cache.set(nodeDid, publicKey);
  }

  /**
   * 获取缓存的公钥，不存在返回 undefined。
   */
  get(nodeDid: string): CryptoKey | undefined {
    return this._cache.get(nodeDid);
  }

  /**
   * 暴露内部缓存 Map 引用，维持兼容性。
   */
  get cacheDict(): Map<string, CryptoKey> {
    return this._cache;
  }

  /**
   * 缓存私钥，后续调用相同标识直接返回缓存。
   */
  cachePrivateKey(keyId: string, privateKey: CryptoKey): void {
    this._privateKeyCache.set(keyId, privateKey);
  }

  /**
   * 获取缓存的私钥。
   */
  getPrivateKey(keyId: string): CryptoKey | undefined {
    return this._privateKeyCache.get(keyId);
  }

  /**
   * 检查是否已有缓存的私钥。
   */
  hasPrivateKey(keyId: string): boolean {
    return this._privateKeyCache.has(keyId);
  }
}