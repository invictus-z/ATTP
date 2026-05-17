/**
 * PEM 密钥导入工具 — 将 PEM 格式密钥导入为 Web Crypto CryptoKey。
 *
 * 支持的密钥类型：
 *   - RSA (RSA-PSS)
 *   - ECDSA (P-256 / P-384 / P-521)
 *
 * 注意：secp256k1 不被 Web Crypto API 原生支持。
 * 如果项目中使用 secp256k1 密钥，建议在配置中指定 key-2 (secp256r1/P-256) 用于签名。
 */

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
 * 从 PEM 字符串导入私钥为 CryptoKey。
 *
 * 自动检测密钥类型（RSA / EC），对 EC 密钥依次尝试 P-256, P-384, P-521。
 *
 * @param pem PEM 格式私钥字符串
 * @returns CryptoKey 私钥对象
 */
export async function importPrivateKeyFromPem(pem: string): Promise<CryptoKey> {
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

  throw new Error('无法导入 EC 私钥：不支持的曲线类型（已尝试 P-256, P-384, P-521）');
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

  throw new Error('无法导入 EC 公钥：不支持的曲线类型');
}