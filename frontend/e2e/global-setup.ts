import { preview } from 'vite'

export default async function globalSetup(){
  const server=await preview({preview:{host:'127.0.0.1',port:52888,strictPort:true}})
  return async()=>{await new Promise<void>((resolve,reject)=>server.httpServer.close(error=>error?reject(error):resolve()))}
}
