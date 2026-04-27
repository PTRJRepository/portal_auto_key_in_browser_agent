export const PLANTWARE_CONFIG = {
  baseUrl: "http://plantwarep3:8001",
  entryUrl: "http://plantwarep3:8001/",
  username: process.env.PLANTWARE_USERNAME ?? "adm075",
  password: process.env.PLANTWARE_PASSWORD ?? "adm075",
  division: process.env.PLANTWARE_DIVISION ?? "P1B",
  listPage: "/en/PR/trx/frmPrTrxADLists.aspx",
  detailPage: "/en/PR/trx/frmPrTrxADDets.aspx",
  maxTabs: 10
};
