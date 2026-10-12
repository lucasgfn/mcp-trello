"""Campos pedidos ao Trello via `fields=` para manter as respostas compactas (RNF06)."""

ORG = "id,name,displayName,desc,url,website"
BOARD = "id,name,desc,closed,url,idOrganization,dateLastActivity"
LIST = "id,name,closed,pos"
LABEL = "id,name,color"
MEMBER = "id,username,fullName"
CARD = "id,name,desc,closed,idBoard,idList,idMembers,labels,due,dueComplete,url,dateLastActivity"
CARD_SHORT = "id,name,closed,idBoard,idList,idMembers,labels,due,dueComplete,url,dateLastActivity"
