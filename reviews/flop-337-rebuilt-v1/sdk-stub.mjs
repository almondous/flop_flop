// Recording boundary only: never imports SDK or connects to RPC.
export const FlopClient={
  create:async opts=>({route:'uri',opts}),
  createWithKeypair:async(rpc,pair)=>({route:'pair',rpc,pair})
};
export const connectFlopApi=()=>{throw Error('read-only SDK connection is out of scope');};
