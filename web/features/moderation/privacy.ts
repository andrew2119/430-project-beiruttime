/** Never paint a cached private preview while its current scope is rechecked or denied. */
export function freshData<T>(state:{data:T|undefined;isFetching:boolean;error:unknown}):T|undefined {
  return state.isFetching||state.error?undefined:state.data;
}
