/** 认证与密钥管理。 */

export { KeyStore } from './keys';
export { signHash, verifySignature, importPublicPem, importPublicJwk } from './signatures';
export {
  resolveDid,
  buildDidResolutionUrl,
  didBaseId,
  extractNodeType,
  clearDidCache,
  invalidateDid,
} from './did-resolver';
export type {
  DidResolutionResult,
  ATTPNodeType,
  ResolveDidOptions,
} from './did-resolver';