/**
 * PEM 密钥导入工具 — 将 PEM 格式密钥导入为可签名对象。
 *
 * 支持的密钥类型：
 *   - RSA (RSA-PSS)
 *   - ECDSA (P-256 / P-384 / P-521) — Web Crypto API 原生
 *   - ECDSA secp256k1 — 通过 @noble/secp256k1
 */

import * as secp from '@noble/secp256k1'

// ---- 可签名密钥类型 ----

/** secp256k1 私钥包装（Web Crypto API 不支持 secp256k1） */
export class Secp256k1PrivateKey {
  readonly keyType = 'secp256k1' as const
  /** 原始私钥字节（32 bytes） */
  readonly rawBytes: Uint8Array

  constructor(bytes: Uint8Array) {
    this.rawBytes = bytes
  }
}

/** 所有可签名密钥的联合类型 */
export type SignableKey = CryptoKey | Secp256k1PrivateKey

/** 类型守卫 */
export function isSecp256k1Key(key: SignableKey): key is Secp256k1PrivateKey {
  return key instanceof Secp256k1PrivateKey
}

// ---- PEM 解析 ----

function pemToBuffer(pem: string): ArrayBuffer {
  const b64 = pem
    .replace(/-----BEGIN.*?-----/g, '')
    .replace(/-----END.*?-----/g, '')
    .replace(/\s/g, '');
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

type KeyType = 'RSA' | 'EC';

function detectKeyType(pem: string): KeyType {
  if (pem.includes('RSA')) return 'RSA';
  return 'EC';
}

/**
 * 检测 EC PEM 是否为 secp256k1 曲线。
 *
 * secp256k1 私钥长度为 32 字节（无 OID 头），PKCS#8 封装后约 46 字节。
 * P-256 私钥长度为 32 字节，但 PKCS#8 封装结构不同（有 OID）。
 *
 * 更可靠的检测方法：尝试 Web Crypto 导入，如果 P-256/P-384/P-521 都失败则判断为 secp256k1。
 */
async function isSecp256k1(buffer: ArrayBuffer): Promise<boolean> {
  const curves: EcKeyImportParams[] = [
    { name: 'ECDSA', namedCurve: 'P-256' },
    { name: 'ECDSA', namedCurve: 'P-384' },
    { name: 'ECDSA', namedCurve: 'P-521' },
  ];
  for (const curve of curves) {
    try {
      await crypto.subtle.importKey('pkcs8', buffer, curve, false, ['sign']);
      return false; // 成功 = 不是 secp256k1
    } catch {
      // continue
    }
  }
  return true; // 所有标准曲线都失败 = 可能是 secp256k1
}

/**
 * 从 PKCS#8 DER buffer 提取 secp256k1 私钥原始字节。
 *
 * PKCS#8 ECPrivateKey 结构：
 *   SEQUENCE {
 *     INTEGER 0              ← version
 *     SEQUENCE { OID }       ← algorithm (可选，secp256k1 可能没有标准 OID)
 *     OCTET STRING {         ← 私钥数据
 *       SEQUENCE {
 *         INTEGER 1          ← EC version
 *         OCTET STRING (32B) ← 私钥值 ← 我们要提取的
 *         [1] ...            ← 公钥（可选）
 *       }
 *     }
 *   }
 */
function extractSecp256k1RawBytes(buffer: ArrayBuffer): Uint8Array {
  const bytes = new Uint8Array(buffer)

  // 直接尝试取最后 32 字节（secp256k1 私钥固定 32 字节）
  // 这是简单策略：PKCS#8 包装后私钥值通常在末尾
  const raw = bytes.slice(-32)
  if (raw.length === 32) return raw

  throw new Error('无法从 PKCS#8 提取 secp256k1 私钥字节')
}

/**
 * 从 PEM 字符串导入私钥为可签名对象。
 *
 * 自动检测密钥类型（RSA / EC），对 EC 密钥依次尝试 P-256, P-384, P-521，
 * 若均失败则尝试 secp256k1（通过 @noble/secp256k1）。
 *
 * @param pem PEM 格式私钥字符串
 * @returns SignableKey（CryptoKey 或 Secp256k1PrivateKey）
 */
export async function importPrivateKeyFromPem(pem: string): Promise<SignableKey> {
  const keyType = detectKeyType(pem);
  const buffer = pemToBuffer(pem);

  if (keyType === 'RSA') {
    return crypto.subtle.importKey(
      'pkcs8',
      buffer,
      { name: 'RSA-PSS', hash: 'SHA-256' },
      false,
      ['sign'],
    );
  }

  // EC key — try P-256, P-384, P-521 in order
  const curves: EcKeyImportParams[] = [
    { name: 'ECDSA', namedCurve: 'P-256' },
    { name: 'ECDSA', namedCurve: 'P-384' },
    { name: 'ECDSA', namedCurve: 'P-521' },
  ];

  for (const curve of curves) {
    try {
      return await crypto.subtle.importKey('pkcs8', buffer, curve, false, ['sign']);
    } catch {
      // try next curve
    }
  }

  // 尝试 secp256k1
  try {
    const rawBytes = extractSecp256k1RawBytes(buffer)
    // 验证私钥有效性
    if (!secp.utils.isValidSecretKey(rawBytes)) {
      throw new Error('提取的 secp256k1 私钥无效')
    }
    console.log('[key_helper] 检测到 secp256k1 密钥，使用 @noble/secp256k1')
    return new Secp256k1PrivateKey(rawBytes)
  } catch (e) {
    throw new Error(`无法导入 EC 私钥：不支持的曲线类型（已尝试 P-256, P-384, P-521, secp256k1）。${e}`)
  }
}

/**
 * 从 PEM 字符串导入公钥为 CryptoKey。
 *
 * @param pem PEM 格式公钥字符串
 * @returns CryptoKey 公钥对象
 */
export async function importPublicKeyFromPem(pem: string): Promise<CryptoKey> {
  const keyType = detectKeyType(pem);
  const buffer = pemToBuffer(pem);

  if (keyType === 'RSA') {
    return crypto.subtle.importKey(
      'spki',
      buffer,
      { name: 'RSA-PSS', hash: 'SHA-256' },
      true,
      ['verify'],
    );
  }

  const curves: EcKeyImportParams[] = [
    { name: 'ECDSA', namedCurve: 'P-256' },
    { name: 'ECDSA', namedCurve: 'P-384' },
    { name: 'ECDSA', namedCurve: 'P-521' },
  ];

  for (const curve of curves) {
    try {
      return await crypto.subtle.importKey('spki', buffer, curve, true, ['verify']);
    } catch {
      // try next curve
    }
  }

  throw new Error('无法导入 EC 公钥：不支持的曲线类型（secp256k1 公钥验签暂不支持 Web Crypto）');
}