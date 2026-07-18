/**
 * DID-wba HTTP Message Signatures (RFC 9421) — 生成与验签。
 *
 * 从 anp.authentication.http_signatures.py 逐行翻译，确保 TS↔Python 字节级互通。
 *   - buildContentDigest / verifyContentDigest : RFC 9530
 *   - generateHttpSignatureHeaders             : 签名（供 client.ts 发送 A2A 请求）
 *   - verifyHttpMessageSignature               : 验签（供 server.ts 接收 A2A 请求）
 *
 * 关键互通点（与核心 signatures.ts 对齐）：
 *   - signRaw 对 ECDSA 输出 raw r‖s（compact）；Python 把 DER 归一化为 compact 上线。
 *     故 TS 侧无需归一化，直接用 signRaw 的输出上线；wire 格式两端一致。
 *   - verifyRaw 接受 raw r‖s（ECDSA），与 Python 的 _verify_signature_bytes
 *     （接受 compact、内部转 DER 验签）一致。
 */

import { createHash, randomBytes } from "node:crypto";
import type { AnyKey } from "../core/authentication/keys.js";
import {
  signRaw,
  verifyRaw,
  importPublicPem,
  importPublicJwk,
  importPublicMultibase,
} from "../core/authentication/signatures.js";

type Bytes = Uint8Array<ArrayBuffer>;
const enc = (s: string): Bytes => new TextEncoder().encode(s);
const b64 = (b: Bytes): string =>
  typeof Buffer !== "undefined"
    ? Buffer.from(b).toString("base64")
    : btoa(String.fromCharCode(...b));
const unb64 = (s: string): Bytes =>
  typeof Buffer !== "undefined"
    ? new Uint8Array(Buffer.from(s, "base64"))
    : (() => {
        const bin = atob(s);
        const u = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
        return u;
      })();

const sha256 = (data: Bytes): Bytes => {
  // Node 同步 SHA-256（保持 build/verify 同步，对齐 Python 的同步行为）
  return new Uint8Array(createHash("sha256").update(data).digest());
};

// ---- RFC 9530 Content-Digest ----

/** 构建 RFC 9530 Content-Digest header 值：`sha-256=:<base64(sha256(body))>:`。 */
export function buildContentDigest(body: Bytes): string {
  const digest = sha256(body);
  return `sha-256=:${b64(digest)}:`;
}

/** 校验 RFC 9530 Content-Digest（对齐 Python verify_content_digest 的 strip 语义）。 */
export function verifyContentDigest(body: Bytes, contentDigest: string): boolean {
  if (!contentDigest) return false;
  return buildContentDigest(body) === contentDigest.trim();
}

// ---- 头部查找 / 组件取值 ----

function getHeaderCaseInsensitive(
  headers: Record<string, string>,
  name: string,
): string | undefined {
  const lower = name.toLowerCase();
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === lower) return headers[key];
  }
  return undefined;
}

function componentValue(
  component: string,
  method: string,
  url: string,
  headers: Record<string, string>,
): string {
  if (component === "@method") return method.toUpperCase();
  if (component === "@target-uri") return url;
  if (component === "@authority") return new URL(url).host; // netloc 等价（含端口）
  const value = getHeaderCaseInsensitive(headers, component);
  if (value === undefined) {
    throw new Error(`Missing covered header component: ${component}`);
  }
  return value;
}

// ---- signature-params 序列化 / 签名基 ----

function serializeSignatureParams(
  components: string[],
  created: number,
  expires: number | null,
  nonce: string | null,
  keyid: string,
): string {
  const quoted = components.map((c) => `"${c}"`).join(" ");
  const params: string[] = [`created=${created}`];
  if (expires !== null) params.push(`expires=${expires}`);
  if (nonce !== null) params.push(`nonce="${nonce}"`);
  params.push(`keyid="${keyid}"`);
  return `(${quoted});` + params.join(";");
}

function buildSignatureBase(
  components: string[],
  method: string,
  url: string,
  headers: Record<string, string>,
  created: number,
  expires: number | null,
  nonce: string | null,
  keyid: string,
): Bytes {
  const signatureParams = serializeSignatureParams(
    components,
    created,
    expires,
    nonce,
    keyid,
  );
  const lines: string[] = [];
  for (const component of components) {
    lines.push(
      `"${component}": ${componentValue(component, method, url, headers)}`,
    );
  }
  lines.push(`"@signature-params": ${signatureParams}`);
  return enc(lines.join("\n"));
}

// ---- 解析 Signature-Input / Signature 头 ----

const SIGNATURE_INPUT_RE =
  /^\s*([a-zA-Z0-9_-]+)=\(([^)]*)\)(.*)$/;
const SIGNATURE_HEADER_RE =
  /^\s*([a-zA-Z0-9_-]+)=:([A-Za-z0-9+/=]+):\s*$/;

interface ParsedSignatureInput {
  label: string;
  components: string[];
  params: Record<string, string | number | boolean>;
}

function parseSignatureInput(signatureInput: string): ParsedSignatureInput {
  const match = SIGNATURE_INPUT_RE.exec(signatureInput.trim());
  if (!match) throw new Error("Invalid Signature-Input header format");
  const label = match[1];
  const componentsRaw = match[2].trim();
  const paramsRaw = match[3];

  const components = Array.from(componentsRaw.matchAll(/"([^"]+)"/g)).map(
    (m) => m[1],
  );
  if (components.length === 0) {
    throw new Error("Signature-Input must include covered components");
  }

  const params: Record<string, string | number | boolean> = {};
  for (const rawParam of paramsRaw.split(";")) {
    const p = rawParam.trim();
    if (!p) continue;
    const eq = p.indexOf("=");
    if (eq === -1) {
      params[p] = true;
      continue;
    }
    const name = p.slice(0, eq).trim();
    let rawValue = p.slice(eq + 1).trim();
    if (rawValue.startsWith('"') && rawValue.endsWith('"')) {
      params[name] = rawValue.slice(1, -1);
    } else {
      const asInt = Number(rawValue);
      params[name] = Number.isInteger(asInt) ? asInt : rawValue;
    }
  }
  return { label, components, params };
}

function parseSignatureHeader(signatureHeader: string): {
  label: string;
  signatureBytes: Bytes;
} {
  const match = SIGNATURE_HEADER_RE.exec(signatureHeader.trim());
  if (!match) throw new Error("Invalid Signature header format");
  return { label: match[1], signatureBytes: unb64(match[2]) };
}

// ---- DID 文档验证方法解析 ----

function findVerificationMethod(
  didDocument: any,
  verificationMethodId: string,
): any | undefined {
  const methods: any[] = didDocument.verificationMethod ?? [];
  for (const m of methods) {
    if (m && typeof m === "object" && m.id === verificationMethodId) return m;
  }
  for (const auth of didDocument.authentication ?? []) {
    if (auth && typeof auth === "object" && auth.id === verificationMethodId) {
      return auth;
    }
    if (typeof auth === "string" && auth === verificationMethodId) {
      for (const m of methods) {
        if (m && typeof m === "object" && m.id === verificationMethodId) {
          return m;
        }
      }
    }
  }
  return undefined;
}

/**
 * 从 DID 文档解析验证方法的公钥。
 *
 * 支持 publicKeyMultibase（ATTP 默认，Ed25519 Multikey；经 importPublicMultibase）、
 * publicKeyPem（经 importPublicPem）与 publicKeyJwk（经 importPublicJwk）。
 * 对齐 Python create_verification_method 支持的 multibase/JWK/PEM 路径。
 */
export async function resolveVerificationPublicKey(
  didDocument: any,
  keyid: string,
): Promise<AnyKey> {
  const methodDict = findVerificationMethod(didDocument, keyid);
  if (!methodDict) {
    throw new Error(`Verification method not found: ${keyid}`);
  }
  if (methodDict.publicKeyMultibase) {
    return importPublicMultibase(methodDict.publicKeyMultibase);
  }
  if (methodDict.publicKeyPem) {
    return importPublicPem(methodDict.publicKeyPem);
  }
  if (methodDict.publicKeyJwk) {
    return importPublicJwk(methodDict.publicKeyJwk);
  }
  throw new Error(
    "Unsupported verification method key format (expected publicKeyMultibase, publicKeyPem or publicKeyJwk)",
  );
}

function resolveKeyId(didDocument: any, explicit?: string): string {
  if (explicit) return explicit;
  const auth: any[] = didDocument.authentication ?? [];
  if (!auth.length) {
    throw new Error("DID document has no authentication methods");
  }
  const first = auth[0];
  if (typeof first === "string") return first;
  if (first && typeof first === "object" && first.id) return first.id;
  throw new Error("Unsupported authentication method shape");
}

function randomHex(bytes: number): string {
  return randomBytes(bytes).toString("hex");
}

// ---- 生成签名头 ----

export interface GenerateHttpSignatureHeadersOptions {
  didDocument: any;
  requestUrl: string;
  requestMethod: string;
  privateKey: AnyKey;
  /** 额外需要覆盖的请求头（如 Authorization）。 */
  headers?: Record<string, string>;
  body?: Bytes;
  keyid?: string;
  nonce?: string;
  created?: number;
  expires?: number;
  coveredComponents?: string[];
}

export interface SignatureHeaders {
  "Signature-Input": string;
  Signature: string;
  "Content-Digest"?: string;
}

/**
 * 生成 RFC 9421 HTTP Message Signature 头。
 *
 * 注意：与 Python（同步、sign_callback 同步）不同，TS 使用 Web Crypto，
 * signRaw 为异步，故本函数返回 Promise。
 */
export async function generateHttpSignatureHeaders(
  opts: GenerateHttpSignatureHeadersOptions,
): Promise<SignatureHeaders> {
  const { didDocument, requestUrl, requestMethod, privateKey } = opts;
  if (!didDocument.id) {
    throw new Error("DID document is missing the id field");
  }

  const keyid = resolveKeyId(didDocument, opts.keyid);
  // 确认 keyid 指向一个存在的验证方法（与 Python 行为一致）
  const methodDict = findVerificationMethod(didDocument, keyid);
  if (!methodDict) {
    throw new Error(`Verification method not found: ${keyid}`);
  }

  const headersToSign: Record<string, string> = { ...(opts.headers ?? {}) };
  const bodyBytes = opts.body ?? new Uint8Array(0);
  const components = opts.coveredComponents
    ? [...opts.coveredComponents]
    : ["@method", "@target-uri", "@authority"];

  if (bodyBytes.length > 0) {
    if (headersToSign["Content-Digest"] === undefined) {
      headersToSign["Content-Digest"] = buildContentDigest(bodyBytes);
    }
    if (!components.some((c) => c.toLowerCase() === "content-digest")) {
      components.push("content-digest");
    }
    if (headersToSign["Content-Length"] === undefined) {
      headersToSign["Content-Length"] = String(bodyBytes.length);
    }
  }

  const created = opts.created ?? Math.floor(Date.now() / 1000);
  const expires = opts.expires ?? created + 300;
  const nonceValue = opts.nonce ?? randomHex(16);

  const signatureBase = buildSignatureBase(
    components,
    requestMethod,
    requestUrl,
    headersToSign,
    created,
    expires,
    nonceValue,
    keyid,
  );

  // signRaw 对 ECDSA 输出 raw r‖s（compact），与 Python 归一化后的上线格式一致。
  const rawSignature = await signRaw(signatureBase, privateKey);

  const signatureInput = `sig1=${serializeSignatureParams(
    components,
    created,
    expires,
    nonceValue,
    keyid,
  )}`;
  const signatureHeader = `sig1=:${b64(rawSignature)}:`;

  const result: SignatureHeaders = {
    "Signature-Input": signatureInput,
    Signature: signatureHeader,
  };
  if (bodyBytes.length > 0) {
    result["Content-Digest"] = headersToSign["Content-Digest"];
  }
  return result;
}

// ---- 验签 ----

export interface SignatureMetadata {
  keyid: string;
  nonce: string | null;
  created: number;
  expires: number | null;
  components: string[];
}

/**
 * 校验 RFC 9421 HTTP Message Signature。
 *
 * 返回 `[ok, message, metadata?]`，与 Python verify_http_message_signature 的
 * `(ok, msg, metadata)` 元组对齐。失败时返回 false（不抛）。
 */
export async function verifyHttpMessageSignature(
  didDocument: any,
  requestMethod: string,
  requestUrl: string,
  headers: Record<string, string>,
  body?: Bytes,
): Promise<[boolean, string, SignatureMetadata?]> {
  try {
    const signatureInput = getHeaderCaseInsensitive(headers, "Signature-Input");
    const signatureHeader = getHeaderCaseInsensitive(headers, "Signature");
    if (!signatureInput || !signatureHeader) {
      return [false, "Missing Signature-Input or Signature header", undefined];
    }

    const { label: labelInput, components, params } = parseSignatureInput(
      signatureInput,
    );
    const { label: labelSig, signatureBytes } = parseSignatureHeader(
      signatureHeader,
    );
    if (labelInput !== labelSig) {
      return [false, "Signature label mismatch", undefined];
    }

    const keyid = params.keyid;
    if (typeof keyid !== "string" || !keyid) {
      return [false, "Signature-Input missing keyid", undefined];
    }

    const methodDict = findVerificationMethod(didDocument, keyid);
    if (!methodDict) {
      return [false, "Verification method not found", undefined];
    }

    const bodyBytes = body ?? new Uint8Array(0);
    const hasContentDigestComponent = components.some(
      (c) => c.toLowerCase() === "content-digest",
    );
    if (bodyBytes.length > 0 || hasContentDigestComponent) {
      const contentDigest = getHeaderCaseInsensitive(headers, "Content-Digest");
      if (!contentDigest) {
        return [false, "Missing Content-Digest header", undefined];
      }
      if (!verifyContentDigest(bodyBytes, contentDigest)) {
        return [false, "Content-Digest verification failed", undefined];
      }
    }

    const created = params.created;
    const expires = params.expires ?? null;
    const nonce = (params.nonce as string | undefined) ?? null;
    if (typeof created !== "number") {
      return [
        false,
        "Signature-Input missing created parameter",
        undefined,
      ];
    }
    if (expires !== null && typeof expires !== "number") {
      return [false, "Invalid expires parameter", undefined];
    }

    const signatureBase = buildSignatureBase(
      components,
      requestMethod,
      requestUrl,
      headers,
      created,
      typeof expires === "number" ? expires : null,
      nonce,
      keyid,
    );

    const pubKey = await resolveVerificationPublicKey(didDocument, keyid);
    const ok = await verifyRaw(signatureBase, signatureBytes, pubKey);
    if (!ok) {
      return [false, "Signature verification failed", undefined];
    }

    return [
      true,
      "Verification successful",
      {
        keyid,
        nonce,
        created,
        expires: typeof expires === "number" ? expires : null,
        components,
      },
    ];
  } catch (exc) {
    return [false, `Verification error: ${(exc as Error).message}`, undefined];
  }
}
