/**
 * DID 文档解析器 — 从 python/attp/core/authentication/did_resolver.py 移植。
 *
 * 提供带 TTL 缓存与重试的 DID 解析能力：
 *   - buildDidResolutionUrl：did:wba/<did:web> → did.json 的 HTTPS URL 构造
 *     （剥离末尾的 e1_/k1_ key identifier 段）。
 *   - resolveDid：解析 DID 文档 → 提取验证公钥 + ATTP 节点类型。
 *
 * 公钥提取（按编码分派，覆盖最常见路径）：
 *   - publicKeyPem  → importPublicPem（RSA / EC P-* / secp256k1 / Ed25519，TS 新增）
 *   - publicKeyJwk  → importPublicJwk（按 kty/crv 分派，与 importPublicPem 一致）
 *   - publicKeyMultibase / publicKeyBase58：暂未移植，抛出明确错误（避免静默 stub）。
 *
 * 节点类型提取：
 *   - 主路径：alsoKnownAs 中的 "ATTPNode:<type>"（openclaw / TS agent DID profile）。
 *   - 兼容路径：service[type="ATTPNodeType"] + serviceEndpoint "attp:type:<type>"
 *     （Python ANP profile，作为回退保留以维持与 Python 互操作）。
 */

import { importPublicPem, importPublicJwk } from "./signatures.js";
import type { AnyKey } from "./keys.js";

// --- 常量 ---

/** Python DIDResolver 默认 TTL（秒）。 */
const DEFAULT_TTL_SECONDS = 300;
/** 重试次数（与 Python 默认 max_retries=2 一致：1 + 2 = 3 次尝试）。 */
const DEFAULT_MAX_RETRIES = 2;
/** 基础退避（毫秒），指数退避 delay = RETRY_BASE_MS * 2^attempt。 */
const RETRY_BASE_MS = 1000;

/** 合法的 ATTP 节点类型。 */
const VALID_NODE_TYPES: ReadonlySet<string> = new Set(["agent", "tool", "user"]);

/**
 * did:wba key identifier 前缀（anp SDK profile：e1=Ed25519、k1=secp256k1；
 * plain_legacy profile 无 key id，末段即普通路径）。本模块不依赖 anp，故硬编码。
 */
const KEY_ID_PREFIXES = ["e1_", "k1_"];

// --- 类型 ---

/** ATTP 节点类型；开放 string 以容忍未来扩展。 */
export type ATTPNodeType = "agent" | "tool" | "user" | (string & {});

export interface DidResolutionResult {
  /** 解析到的 DID 文档。 */
  didDocument: any;
  /** 从 verificationMethod 提取的公钥；缺失/不支持时为 null。 */
  publicKey: AnyKey | null;
  /** 从 alsoKnownAs / service 提取的节点类型；未识别时为 null。 */
  nodeType: ATTPNodeType | null;
  /** 命中缓存时为 true。 */
  fromCache: boolean;
}

interface CacheEntry {
  didDocument: any;
  publicKey: AnyKey | null;
  nodeType: ATTPNodeType | null;
  /** 失效时刻（Date.now() 毫秒）。 */
  expiresAt: number;
}

// --- 模块级缓存 ---

const cache = new Map<string, CacheEntry>();

/**
 * 清空整个 DID 解析缓存。主要用于测试隔离。
 */
export function clearDidCache(): void {
  cache.clear();
}

/**
 * 失效指定 DID 的缓存条目（Python `invalidate` 对应）。
 */
export function invalidateDid(did: string): void {
  cache.delete(did);
}

// --- URL 构造（移植自 build_did_resolution_url）---

/**
 * 剥离末尾连续的 did:wba key identifier 段（e1_/k1_ 前缀）；无则原样返回。
 */
function dropTrailingKeyId(parts: string[]): string[] {
  const result = [...parts];
  while (
    result.length > 0 &&
    KEY_ID_PREFIXES.some((p) => result[result.length - 1].startsWith(p))
  ) {
    result.pop();
  }
  return result;
}

/**
 * 返回 DID 的基础标识（去除末尾的 key identifier，若存在）。
 *   did:wba:host:p1:p2:e1_key → did:wba:host:p1:p2
 *   did:wba:host:p1:p2        → did:wba:host:p1:p2（无 key id）
 */
export function didBaseId(did: string): string {
  return dropTrailingKeyId(did.split(":")).join(":");
}

/**
 * 构建 DID 文档的 HTTPS 解析 URL。
 *
 * DID 格式: did:wba:<domain>[:<path>...][:<key_identifier>]
 * key identifier 可选，按 e1_/k1_ 前缀识别并剥离；其余段 unquote（URL 解码）后拼为路径。
 *   did:wba:host:p1:p2:e1_key → https://host/p1/p2/did.json
 *   did:wba:host:p1:p2        → https://host/p1/p2/did.json（无 key id）
 *   did:wba:host:e1_key       → https://host/.well-known/did.json
 *
 * 注：Python 用 urllib.parse.unquote，仅解码 %XX 不把 '+' 视作空格；
 * JS decodeURIComponent 行为一致。
 */
export function buildDidResolutionUrl(
  did: string,
  baseUrlOverride?: string,
): string {
  const parts = did.split(":");
  if (parts.length < 3 || parts[0] !== "did") {
    throw new Error("Invalid DID format");
  }
  const method = parts[1];
  if (method !== "wba" && method !== "web") {
    throw new Error(`Unsupported DID method: ${method}`);
  }
  const domain = decodeURIComponent(parts[2]);
  const rawSegments = dropTrailingKeyId(parts.slice(3));
  const pathSegments = rawSegments.map((seg) => decodeURIComponent(seg));
  const baseUrl = (baseUrlOverride ?? `https://${domain}`).replace(/\/+$/, "");
  if (pathSegments.length > 0) {
    return `${baseUrl}/${pathSegments.join("/")}/did.json`;
  }
  return `${baseUrl}/.well-known/did.json`;
}

// --- 节点类型提取 ---

/**
 * 从 DID 文档提取 ATTPNodeType。
 *
 * 主路径（openclaw/TS profile）：alsoKnownAs 中形如 "ATTPNode:<type>" 的条目。
 * 回退路径（Python ANP profile）：service 中 type="ATTPNodeType" 且
 *   serviceEndpoint 形如 "attp:type:<type>"。
 */
export function extractNodeType(didDoc: any): ATTPNodeType | null {
  // 主路径：alsoKnownAs
  const alsoKnownAs: unknown[] = Array.isArray(didDoc?.alsoKnownAs)
    ? didDoc.alsoKnownAs
    : [];
  for (const entry of alsoKnownAs) {
    if (typeof entry === "string" && entry.startsWith("ATTPNode:")) {
      const t = entry.slice("ATTPNode:".length);
      if (VALID_NODE_TYPES.has(t)) return t;
    }
  }

  // 回退路径：service[type="ATTPNodeType"]（保持与 Python 互操作）
  const services: any[] = Array.isArray(didDoc?.service) ? didDoc.service : [];
  for (const svc of services) {
    if (svc?.type === "ATTPNodeType") {
      const endpoint =
        typeof svc.serviceEndpoint === "string" ? svc.serviceEndpoint : "";
      if (endpoint.startsWith("attp:type:")) {
        const t = endpoint.slice("attp:type:".length);
        if (VALID_NODE_TYPES.has(t)) return t;
      }
    }
  }
  return null;
}

// --- 公钥提取 ---

/**
 * 从 verificationMethod 提取公钥。按编码分派：
 *   publicKeyPem  → importPublicPem（TS 新增，覆盖 RSA/EC/secp256k1/Ed25519）
 *   publicKeyJwk  → importPublicJwk（按 kty/crv 分派）
 *   publicKeyMultibase / publicKeyBase58 → 暂不支持，抛出明确错误
 *
 * 注：Python 按验证方法 *类型*（EcdsaSecp256k1VerificationKey2019 等）分派且不
 * 处理 publicKeyPem；TS 采用按编码分派，更宽松地覆盖各种 method type，使 PEM
 * 路径可用（openclaw DID 文档常用 JsonWebKey2020 + publicKeyPem）。
 */
async function extractPublicKey(verificationMethod: any): Promise<AnyKey> {
  const methodType: string | undefined = verificationMethod?.type;
  if (!methodType) {
    throw new Error("Verification method missing 'type' field");
  }

  // PEM 路径（TS 新增）
  if (typeof verificationMethod.publicKeyPem === "string") {
    return importPublicPem(verificationMethod.publicKeyPem);
  }

  // JWK 路径
  if (
    verificationMethod.publicKeyJwk &&
    typeof verificationMethod.publicKeyJwk === "object"
  ) {
    return importPublicJwk(
      verificationMethod.publicKeyJwk as JsonWebKey,
    );
  }

  // multibase / base58：暂未移植
  if (
    verificationMethod.publicKeyMultibase !== undefined ||
    verificationMethod.publicKeyBase58 !== undefined
  ) {
    throw new Error(
      "Unsupported verification method encoding: publicKeyMultibase / publicKeyBase58 " +
        "are not yet implemented in the TS DIDResolver port. " +
        "Use publicKeyJwk or publicKeyPem in the DID document.",
    );
  }

  throw new Error(
    `Unsupported verification method type or missing required key format: ${methodType}`,
  );
}

/**
 * 在 DID 文档中按 key id 查找 verificationMethod。
 * 依次搜索 verificationMethod、authentication、assertionMethod（与 Python 一致）。
 */
function findVerificationMethod(
  didDocument: any,
  verificationMethodId: string,
): any | null {
  const vm: any[] = Array.isArray(didDocument?.verificationMethod)
    ? didDocument.verificationMethod
    : [];

  for (const m of vm) {
    if (m?.id === verificationMethodId) return m;
  }

  const lookup = (arr: any): any | null => {
    if (!Array.isArray(arr)) return null;
    for (const a of arr) {
      if (typeof a === "string") {
        if (a === verificationMethodId) {
          for (const m of vm) {
            if (m?.id === verificationMethodId) return m;
          }
        }
      } else if (a && typeof a === "object" && a.id === verificationMethodId) {
        return a;
      }
    }
    return null;
  };

  const fromAuth = lookup(didDocument?.authentication);
  if (fromAuth) return fromAuth;

  const fromAssertion = lookup(didDocument?.assertionMethod);
  if (fromAssertion) return fromAssertion;

  return null;
}

// --- 主解析入口 ---

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

export interface ResolveDidOptions {
  /** verificationMethod 的 key fragment（默认 "key-1"）。 */
  keyFragment?: string;
  /** 覆盖基准 URL（测试/定制发现端点用）。 */
  baseUrlOverride?: string;
  /** 缓存 TTL（秒），默认 300。 */
  ttlSeconds?: number;
  /** 最大重试次数，默认 2。 */
  maxRetries?: number;
  /** 跳过 DID 文档 id 一致性校验（宽松模式）。 */
  skipIdCheck?: boolean;
}

/**
 * 解析 DID → { didDocument, publicKey, nodeType }。
 *
 * 带模块级 TTL 缓存与指数退避重试（仅在网络错误 / 非 2xx 时重试）。
 * 公钥提取失败（如不支持的编码）不抛出，而是返回 publicKey=null，便于上层降级。
 */
export async function resolveDid(
  did: string,
  opts: ResolveDidOptions = {},
): Promise<DidResolutionResult> {
  const keyFragment = opts.keyFragment ?? "key-1";
  const ttl = opts.ttlSeconds ?? DEFAULT_TTL_SECONDS;
  const maxRetries = opts.maxRetries ?? DEFAULT_MAX_RETRIES;

  // 缓存命中
  const cached = cache.get(did);
  if (cached && cached.expiresAt > Date.now()) {
    return {
      didDocument: cached.didDocument,
      publicKey: cached.publicKey,
      nodeType: cached.nodeType,
      fromCache: true,
    };
  }

  // 网络解析 + 重试
  const url = buildDidResolutionUrl(did, opts.baseUrlOverride);
  let lastError: Error | null = null;
  let didDocument: any = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
      });
      if (!response || !response.ok) {
        const status = response ? response.status : 0;
        lastError = new Error(`HTTP ${status} for ${url}`);
        if (attempt < maxRetries) {
          await sleep(RETRY_BASE_MS * 2 ** attempt);
          continue;
        }
        break;
      }
      didDocument = await response.json();

      // DID 文档 id 一致性校验（移植自 Python resolve_did_document）
      if (!opts.skipIdCheck) {
        const docId: string = didDocument?.id ?? "";
        if (
          docId &&
          docId !== did &&
          docId !== didBaseId(did) &&
          didBaseId(docId) !== didBaseId(did)
        ) {
          throw new Error(
            `DID document ID mismatch. Expected: ${did} (or base ${didBaseId(
              did,
            )}), got: ${docId}`,
          );
        }
      }
      break; // 成功
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));
      if (attempt < maxRetries) {
        await sleep(RETRY_BASE_MS * 2 ** attempt);
      }
    }
  }

  if (!didDocument) {
    throw new Error(
      `DID resolution failed for ${did} after ${maxRetries + 1} attempt(s): ${
        lastError?.message ?? lastError
      }`,
    );
  }

  // 提取公钥
  const keyId = `${did}#${keyFragment}`;
  const method = findVerificationMethod(didDocument, keyId);
  let publicKey: AnyKey | null = null;
  if (method) {
    try {
      publicKey = await extractPublicKey(method);
    } catch {
      // 提取失败（不支持的编码等）→ publicKey 保持 null，便于上层降级
      publicKey = null;
    }
  }

  // 提取节点类型
  const nodeType = extractNodeType(didDocument);

  // 写缓存
  cache.set(did, {
    didDocument,
    publicKey,
    nodeType,
    expiresAt: Date.now() + ttl * 1000,
  });

  return { didDocument, publicKey, nodeType, fromCache: false };
}
