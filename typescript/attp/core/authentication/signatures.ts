/**
 * 签名与验签引擎（与 python/attp/core/authentication/signatures.py 逐字节互通）。
 * 签名对象恒为 data 的 UTF-8 字节；签名输出/输入：signRaw/verifyRaw 用原始字节，
 * signHash/verifySignature 用 base64（核心 ATTP 用）。
 *   RSA-PSS        : MGF1-SHA256，saltLength = MAX（modulusBytes - 32 - 2，对齐 Python PSS.MAX_LENGTH）
 *   ECDSA P-256/384/521 : Web Crypto。TS 输出 raw r‖s；验签时把 Python 的 DER 转 raw。
 *   secp256k1      : @noble/curves（输出 raw r‖s，prehash=SHA256 对齐 Python ECDSA(SHA256())）
 *   Ed25519        : @noble/ed25519（纯 EdDSA，对字节直接签）
 */
import * as ed from "@noble/ed25519";
import { secp256k1 } from "@noble/curves/secp256k1";
import type { AnyKey, NobleKey } from "./keys.js";

type Bytes = Uint8Array<ArrayBuffer>;
const enc = (s: string): Bytes => new TextEncoder().encode(s);
const b64 = (b: Bytes | ArrayBuffer): string =>
  typeof Buffer !== "undefined"
    ? Buffer.from(b instanceof Uint8Array ? b : new Uint8Array(b)).toString("base64")
    : btoa(String.fromCharCode(...(b instanceof Uint8Array ? b : new Uint8Array(b))));
const unb64 = (s: string): Bytes =>
  typeof Buffer !== "undefined"
    ? new Uint8Array(Buffer.from(s, "base64"))
    : (() => {
        const bin = atob(s);
        const u = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
        return u;
      })();
const b64u = (s: string): Bytes => {
  const pad = s + "=".repeat((4 - (s.length % 4)) % 4);
  return unb64(pad.replace(/-/g, "+").replace(/_/g, "/"));
};

const subtle: SubtleCrypto = globalThis.crypto.subtle;
const ecFieldBytes: Record<string, number> = { "P-256": 32, "P-384": 48, "P-521": 66 };

const isNoble = (k: AnyKey): k is NobleKey =>
  !!k && typeof k === "object" && "kind" in k;

/** DER(SEQUENCE{r,s}) -> raw r‖s，左填充到 fieldBytes。曲线无关 ASN.1 解析。 */
function derToCompact(der: Bytes, fieldBytes: number): Bytes {
  let i = 0;
  if (der[i++] !== 0x30) throw new Error("not DER");
  // 跳过 SEQUENCE 长度（短形式 1 字节；长形式 0x80|n 后跟 n 字节）
  i += der[i] & 0x80 ? (der[i] & 0x7f) + 1 : 1;
  const readInt = (): Bytes => {
    if (der[i++] !== 0x02) throw new Error("expected INTEGER");
    const len = der[i++];
    const v = der.subarray(i, i + len);
    i += len;
    return v[0] === 0 ? v.subarray(1) : v; // 去前导 0
  };
  const r = readInt();
  const s = readInt();
  const out = new Uint8Array(fieldBytes * 2);
  out.set(r, fieldBytes - r.length);
  out.set(s, fieldBytes * 2 - s.length);
  return out;
}

/** RSA-PSS MAX salt length = modulusBytes - hashLen - 2（对齐 Python PSS.MAX_LENGTH）。 */
async function rsaMaxSalt(key: CryptoKey): Promise<number> {
  const jwk = (await subtle.exportKey("jwk", key)) as JsonWebKey;
  const modulusBytes = Math.floor(((jwk.n ?? "").length * 3) / 4);
  return Math.max(0, modulusBytes - 32 - 2);
}

/** 字节级签名（DID-wba HTTP 签名用）。 */
export async function signRaw(data: Bytes, key: AnyKey): Promise<Bytes> {
  if (isNoble(key)) {
    if (key.kind === "ed25519") return (await ed.signAsync(data, key.priv!)) as Bytes;
    // prehash=true: noble 默认 prehash=false（不哈希），需显式开启以对齐 Python ECDSA(SHA256())
    return secp256k1.sign(data, key.priv!, { prehash: true }).toCompactRawBytes() as Bytes;
  }
  const alg = (key.algorithm as { name: string }).name;
  if (alg === "RSA-PSS")
    return new Uint8Array(
      await subtle.sign({ name: "RSA-PSS", saltLength: await rsaMaxSalt(key) }, key, data),
    );
  if (alg === "ECDSA")
    return new Uint8Array(
      await subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, data),
    ); // raw r‖s (P1363)
  throw new Error(`unsupported sign key: ${alg}`);
}

/** 字节级验签。 */
export async function verifyRaw(data: Bytes, sig: Bytes, key: AnyKey): Promise<boolean> {
  try {
    if (isNoble(key)) {
      if (key.kind === "ed25519") return await ed.verifyAsync(sig, data, key.pub!);
      // noble verify 自动识别 DER / compact 格式；prehash=true 对齐 Python ECDSA(SHA256())；
      // lowS=false 接受 high-s（Python cryptography 不做 low-s 归一化）
      return secp256k1.verify(sig, data, key.pub!, { prehash: true, lowS: false });
    }
    const alg = key.algorithm as { name: string; namedCurve?: string };
    if (alg.name === "RSA-PSS")
      return await subtle.verify(
        { name: "RSA-PSS", saltLength: await rsaMaxSalt(key) },
        key,
        sig,
        data,
      );
    if (alg.name === "ECDSA") {
      const fb = ecFieldBytes[alg.namedCurve ?? ""] ?? 32;
      // 先尝试 raw r‖s（TS 原生输出）
      if (await subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, sig, data)) return true;
      // Python 输出 DER — 转 raw 后重试
      if (sig[0] === 0x30)
        return await subtle.verify(
          { name: "ECDSA", hash: "SHA-256" },
          key,
          derToCompact(sig, fb),
          data,
        );
      return false;
    }
    return false;
  } catch {
    return false;
  }
}

/** ATTP 核心用：对 entryHash 字符串签名，返回 base64。 */
export async function signHash(entryHash: string, key: AnyKey): Promise<string> {
  try {
    return b64(await signRaw(enc(entryHash), key));
  } catch {
    return "";
  }
}

export async function verifySignature(
  entryHash: string,
  signatureB64: string,
  key: AnyKey,
): Promise<boolean> {
  return verifyRaw(enc(entryHash), unb64(signatureB64), key);
}

/** 从 PEM 加载公钥为 AnyKey。 */
export async function importPublicPem(pem: string): Promise<AnyKey> {
  const { createPublicKey } = await import("node:crypto");
  const ko = createPublicKey(pem);
  const jwk = ko.export({ format: "jwk" }) as JsonWebKey;
  const keyType = (ko.asymmetricKeyType ?? "").toString();
  if (keyType === "rsa")
    return subtle.importKey(
      "jwk",
      jwk,
      { name: "RSA-PSS", hash: "SHA-256" },
      true,
      ["verify"],
    ) as Promise<CryptoKey>;
  if (keyType === "ec" && jwk.crv === "secp256k1") {
    const pub = new Uint8Array(65);
    pub[0] = 0x04;
    pub.set(b64u(jwk.x!), 1);
    pub.set(b64u(jwk.y!), 33);
    return { kind: "secp256k1", pub, algorithm: { name: "secp256k1" } };
  }
  if (keyType === "ec")
    return subtle.importKey(
      "jwk",
      jwk,
      { name: "ECDSA", namedCurve: jwk.crv as string, hash: "SHA-256" },
      true,
      ["verify"],
    ) as Promise<CryptoKey>;
  // okp (ed25519)
  return { kind: "ed25519", pub: b64u(jwk.x!), algorithm: { name: "Ed25519" } };
}

/**
 * 从 JWK 加载公钥为 AnyKey。按 kty/crv 分派，与 importPublicPem 路由一致：
 *   RSA          → Web Crypto RSA-PSS
 *   EC secp256k1 → NobleKey（Web Crypto 不支持）
 *   EC P-*       → Web Crypto ECDSA
 *   OKP Ed25519  → NobleKey
 * 用于 DID 文档 publicKeyJwk 解析（did-resolver）。
 */
export async function importPublicJwk(jwk: JsonWebKey): Promise<AnyKey> {
  const kty = jwk.kty;
  if (kty === "RSA") {
    return subtle.importKey(
      "jwk",
      jwk,
      { name: "RSA-PSS", hash: "SHA-256" },
      true,
      ["verify"],
    ) as Promise<CryptoKey>;
  }
  if (kty === "EC") {
    if (jwk.crv === "secp256k1") {
      const pub = new Uint8Array(65);
      pub[0] = 0x04;
      pub.set(b64u(jwk.x!), 1);
      pub.set(b64u(jwk.y!), 33);
      return { kind: "secp256k1", pub, algorithm: { name: "secp256k1" } };
    }
    return subtle.importKey(
      "jwk",
      jwk,
      { name: "ECDSA", namedCurve: jwk.crv as string, hash: "SHA-256" },
      true,
      ["verify"],
    ) as Promise<CryptoKey>;
  }
  if (kty === "OKP" && jwk.crv === "Ed25519") {
    return { kind: "ed25519", pub: b64u(jwk.x!), algorithm: { name: "Ed25519" } };
  }
  throw new Error(`Unsupported JWK: kty=${kty ?? "n/a"}, crv=${jwk.crv ?? "n/a"}`);
}

// ---- base58btc / multibase（对齐 Python base58 + verification_methods.py）----

const BASE58_BTC_ALPHABET =
  "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

/** base58btc 解码（Bitcoin 字母表）。用于 multibase 'z' 前缀串。 */
function base58btcDecode(str: string): Uint8Array {
  const bytes: number[] = [0];
  for (const ch of str) {
    let carry = BASE58_BTC_ALPHABET.indexOf(ch);
    if (carry < 0) throw new Error(`invalid base58btc char: ${ch}`);
    for (let j = 0; j < bytes.length; j++) {
      carry += bytes[j] * 58;
      bytes[j] = carry & 0xff;
      carry >>= 8;
    }
    while (carry > 0) {
      bytes.push(carry & 0xff);
      carry >>= 8;
    }
  }
  // 前导 '1' → 前导零字节（base58btc 语义）
  let leadingZeros = 0;
  for (const ch of str) {
    if (ch === "1") leadingZeros++;
    else break;
  }
  const out = new Uint8Array(bytes.length + leadingZeros);
  for (let i = 0; i < bytes.length; i++) out[out.length - 1 - i] = bytes[i];
  return out;
}

/**
 * 从 multibase 公钥串加载为 AnyKey。
 *
 * 镜像 anp verification_methods.py 的 Ed25519VerificationKey2018
 * ._extract_public_key_from_multibase：base58btc 解码 'z' 后内容，识别
 * Ed25519 Multikey 的 multicodec 前缀 0xed01，剥离得 32 字节原始公钥。
 *   z6Mk… → 0xed01 ‖ <32B Ed25519 pub>
 *
 * 同时容忍裸 32 字节（无前缀）Ed25519 公钥。其它曲线/前缀暂不支持
 * （ATTP 的 EC 验证方法走 publicKeyJwk，不走 multibase）。
 */
export async function importPublicMultibase(multibase: string): Promise<AnyKey> {
  if (!multibase || !multibase.startsWith("z")) {
    throw new Error("Unsupported multibase encoding (expected base58btc 'z' prefix)");
  }
  const decoded = base58btcDecode(multibase.slice(1));
  // Ed25519 Multikey：multicodec 0xed01 + 32 字节原始公钥
  if (decoded.length === 34 && decoded[0] === 0xed && decoded[1] === 0x01) {
    return {
      kind: "ed25519",
      pub: decoded.slice(2),
      algorithm: { name: "Ed25519" },
    };
  }
  // 防御：裸 32 字节 Ed25519
  if (decoded.length === 32) {
    return { kind: "ed25519", pub: decoded, algorithm: { name: "Ed25519" } };
  }
  throw new Error(
    `Unsupported publicKeyMultibase: decoded ${decoded.length} bytes (only Ed25519 0xed01 supported)`,
  );
}
