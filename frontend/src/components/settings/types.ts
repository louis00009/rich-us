// 设置页共享类型
export interface BrokerCfg {
  provider: 'simulated' | 'ibkr'
  host: string
  port: number
  client_id: number
  account: string
  connection_type: 'tws' | 'gateway'
  readonly: boolean
  market_data_type: number
  use_rth: boolean
}
