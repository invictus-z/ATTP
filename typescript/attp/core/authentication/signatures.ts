/**
 * 签名与验签引擎。
 *
 * 从 python/attp/core/authentication/signatures.py 翻译而来。
 * 使用 Web Crypto API 实现，支持：
 *   - RSA-PSS (对应 Python rsa.RSAPrivateKey/RSAPublicKey)
 *   - ECDSA P-256/384/521 (对应 Python ec.EllipticCurvePrivateKey)
 *
 * 注意：Python 端对 entry_hash 字符串直接签名（UTF-8 编码后），
 * Web Crypto API 签名时也对 UTF-8 编码的字符串签名，保持一致。
 */

/**
 * 使用私钥对 entryHash 签名，返回 Base64 编码的签名字符串。
 *
 * @param entryHash SHA-256 hex 字符串
 * @param privateKey CryptoKey 私钥对象 (RSA 或 EC)
 * @returns Base64 编码的签名字符串，失败返回空字符串
 */
export async function signHash(
  entryHash: string,
  privateKey: CryptoKey,
): Promise<string> {
  try {
    const data = new TextEncoder().encode(entryHash);

    let signature: ArrayBuffer;

    const algorithm = privateKey.algorithm;
    if (algorithm.name === 'RSA-PSS') {
      signature = await crypto.subtle.sign(
        {
          name: 'RSA-PSS',
          saltLength: 32, // PSS.MAX_LENGTH 在浏览器端无法直接获取，使用 32 (SHA-256 摘要长度)
        },
        privateKey,
        data,
      );
    } else if (algorithm.name === 'ECDSA') {
      signature = await crypto.subtle.sign(
        {
          name: 'ECDSA',
          hash: 'SHA-256',
        },
        privateKey,
        data,
      );
    } else {
      console.error(`[signatures] Unsupported key type: ${algorithm.name}`);
      return '';
    }

    // 转为 Base64
    return arrayBufferToBase64(signature);
  } catch (e) {
    console.error('[signatures] signHash error:', e);
    return '';
  }
}

/**
 * 用公钥验证 entryHash 的签名。
 *
 * @param entryHash SHA-256 hex 字符串
 * @param signatureB64 Base64 编码的签名
 * @param publicKey CryptoKey 公钥对象
 * @returns true 签名合法，false 验证失败
 */
export async function verifySignature(
  entryHash: string,
  signatureB64: string,
  publicKey: CryptoKey,
): Promise<boolean> {
  try {
    const sigBytes = base64ToArrayBuffer(signatureB64);
    const data = new TextEncoder().encode(entryHash);

    const algorithm = publicKey.algorithm;
    if (algorithm.name === 'RSA-PSS') {
      return await crypto.subtle.verify(
        {
          name: 'RSA-PSS',
          saltLength: 32,
        },
        publicKey,
        sigBytes,
        data,
      );
    } else if (algorithm.name === 'ECDSA') {
      return await crypto.subtle.verify(
        {
          name: 'ECDSA',
          hash: 'SHA-256',
        },
        publicKey,
        sigBytes,
        data,
      );
    } else {
      console.error(`[signatures] Unsupported key type: ${algorithm.name}`);
      return false;
    }
  } catch {
    return false;
  }
}

// ---- 辅助函数 ----

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}