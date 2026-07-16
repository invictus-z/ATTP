/**
 * 密钥管理 — KeyStore 用于缓存公钥/私钥；loadPrivateKeyPem 将 PEM 私钥
 * 加载成统一的 LoadedKey（Node Web Crypto 的 CryptoKey，或 secp256k1/Ed25519
 * 的 NobleKey 原始字节——这两种曲线 Web Crypto 不支持）。
 *
 * 从 python/attp/core/authentication/keys.py 翻译并扩展而来。
 */

import { secp256k1 } from "@noble/curves/secp256k1";

/**
 * Noble 风格的原始字节密钥——用于 Web Crypto 不支持的曲线
 * (secp256k1, Ed25519)。`priv` / `pub` 均为未压缩 / 原始字节。
 */
export interface NobleKey {
  kind: "secp256k1" | "ed25519";
  priv?: Uint8Array;
  pub?: Uint8Array;
  algorithm: { name: string };
}

/**
 * 任意支持的密钥形态：Web Crypto CryptoKey 或 NobleKey。
 */
export type AnyKey = CryptoKey | NobleKey;

/**
 * loadPrivateKeyPem 的返回类型（AnyKey 的别名）。
 */
export type LoadedKey = AnyKey;

/**
 * 密钥存储：管理公钥缓存 (nodeDid → publicKey) 和私钥缓存 (path → privateKey)。
 *
 * 缓存值类型为 LoadedKey，可承载 CryptoKey 或 NobleKey。
 */
export class KeyStore {
  private _cache: Map<string, LoadedKey> = new Map();
  private _privateKeyCache: Map<string, LoadedKey> = new Map();

  /**
   * 注入公钥到缓存。
   */
  cachePublicKey(nodeDid: string, publicKey: LoadedKey): void {
    this._cache.set(nodeDid, publicKey);
  }

  /**
   * 获取缓存的公钥，不存在返回 undefined。
   */
  get(nodeDid: string): LoadedKey | undefined {
    return this._cache.get(nodeDid);
  }

  /**
   * 暴露内部缓存 Map 引用，维持兼容性。
   */
  get cacheDict(): Map<string, LoadedKey> {
    return this._cache;
  }

  /**
   * 缓存私钥，后续调用相同标识直接返回缓存。
   */
  cachePrivateKey(keyId: string, privateKey: LoadedKey): void {
    this._privateKeyCache.set(keyId, privateKey);
  }

  /**
   * 获取缓存的私钥。
   */
  getPrivateKey(keyId: string): LoadedKey | undefined {
    return this._privateKeyCache.get(keyId);
  }

  /**
   * 检查是否已有缓存的私钥。
   */
  hasPrivateKey(keyId: string): boolean {
    return this._privateKeyCache.has(keyId);
  }
}

/**
 * 将 PEM 格式（PKCS8/PKCS1/SEC1）私钥加载为统一的 LoadedKey。
 *
 * - RSA → Web Crypto RSA-PSS CryptoKey
 * - EC P-256/384/521 → Web Crypto ECDSA CryptoKey
 * - EC secp256k1 → NobleKey（Web Crypto 不支持 secp256k1）
 * - OKP Ed25519 → NobleKey（Node Web Crypto 在旧版本上不便支持，统一走 Noble）
 */
export async function loadPrivateKeyPem(pem: string): Promise<LoadedKey> {
  const { createPrivateKey } = await import("node:crypto");
  const ko = createPrivateKey(pem);

  const jwk = ko.export({ format: "jwk" }) as JsonWebKey;
  const subtle = globalThis.crypto.subtle;
  const keyType = ko.asymmetricKeyType;

  if (keyType === "rsa") {
    return subtle.importKey(
      "jwk",
      jwk,
      { name: "RSA-PSS", hash: "SHA-256" },
      true,
      ["sign"],
    );
  }

  if (keyType === "ec") {
    if (jwk.crv === "secp256k1") {
      const priv = b64u(jwk.d);
      const pub = secp256k1.getPublicKey(priv, false);
      return {
        kind: "secp256k1",
        priv,
        pub,
        algorithm: { name: "secp256k1" },
      };
    }
    // P-256 / P-384 / P-521 — Web Crypto ECDSA
    return subtle.importKey(
      "jwk",
      jwk,
      { name: "ECDSA", namedCurve: jwk.crv as string, hash: "SHA-256" },
      true,
      ["sign"],
    );
  }

  // okp (ed25519)
  return {
    kind: "ed25519",
    priv: b64u(jwk.d),
    pub: b64u(jwk.x),
    algorithm: { name: "Ed25519" },
  };
}

// ---- 辅助函数 ----

/**
 * base64url → Uint8Array。处理 padding 与 URL-safe 字符集。
 */
function b64u(s: string | undefined): Uint8Array {
  if (!s) return new Uint8Array(0);
  let str = s.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4 !== 0) str += "=";
  const bin = Buffer.from(str, "base64");
  return new Uint8Array(bin);
}
