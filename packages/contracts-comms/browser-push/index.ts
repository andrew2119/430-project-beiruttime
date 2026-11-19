export type PushResult = {schema_version:'browser-push.v1'; operation_id:string; device_id:string; state:'active'|'revoked'; revision:number};
export type Device = {state:'active'|'revoked'|'unbound';revision:number};
export type PushCommand = {schema_version:'browser-push.v1'; operation_id:string; device_id:string; expected_revision:number; action:'opt_in'|'revoke'|'rebind'; permission:NotificationPermission; subscription:{endpoint:string;p256dh:string;auth:string}|null};
export const operations = {config:'/v1/browser-push/config',command:'/v1/browser-push/devices',lookup:'/v1/browser-push/operations/',device:'/v1/browser-push/devices/',click:'/v1/browser-push/notices/'} as const;
