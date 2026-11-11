import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _numero(valor: Any) -> Optional[float]:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _quantidade_empenhada(valor: Any, valor_unitario: Optional[float]) -> Optional[float]:
    valor_numero = _numero(valor)
    if valor_numero is None or not valor_unitario:
        return None
    return valor_numero / valor_unitario


def _preparar_relatorio(dados: Dict[str, Any]) -> Dict[str, Any]:
    itens: List[Dict[str, Any]] = []
    soma_empenhada = 0.0
    soma_estimada = 0.0
    soma_homologada = 0.0
    registros_vinculados = set()

    for item in dados.get("itens_mapeados", []):
        resultados = item.get("resultados", []) or []
        cnpjs_vencedores = {
            re.sub(r"\D", "", str(resultado.get("niFornecedor") or ""))
            for resultado in resultados
        }
        valores_unitarios = {
            re.sub(r"\D", "", str(resultado.get("niFornecedor") or "")): _numero(
                resultado.get("valorUnitarioHomologado")
            )
            for resultado in resultados
        }

        linhas_empenho = []
        total_empenhado_item = 0.0
        quantidade_empenhada_item = 0.0
        possui_quantidade_empenhada = False

        for empenho_item in item.get("empenhos", []) or []:
            documento = empenho_item.get("item_despesa", {})
            valor_empenhado = _numero(
                documento.get("valorAtual") or empenho_item.get("valor_empenhado")
            )
            fornecedor = re.sub(r"\D", "", str(empenho_item.get("fornecedor_cnpj") or ""))
            valor_unitario = valores_unitarios.get(fornecedor)
            quantidade = _quantidade_empenhada(valor_empenhado, valor_unitario)

            if valor_empenhado is not None:
                total_empenhado_item += valor_empenhado
            if quantidade is not None:
                quantidade_empenhada_item += quantidade
                possui_quantidade_empenhada = True
            registros_vinculados.add(empenho_item.get("numero_empenho"))
            linhas_empenho.append(
                {
                    "numero": empenho_item.get("numero_empenho"),
                    "data": empenho_item.get("data_emissao"),
                    "fornecedor": empenho_item.get("nome_fornecedor"),
                    "valor": valor_empenhado,
                    "quantidade_estimada": quantidade,
                    "descricao": documento.get("descricao"),
                    "valor_unitario_homologado": valor_unitario,
                    "codigo_documento": documento.get("codigoItemEmpenho"),
                }
            )

        valor_estimado = _numero(item.get("valor_total_estimado")) or 0
        valor_homologado = _numero(item.get("valor_total_homologado")) or 0
        quantidade_licitada = _numero(item.get("quantidade_licitada"))
        quantidade_homologada = _numero(item.get("quantidade_homologada"))
        unidade = item.get("unidade_medida") or ""

        soma_estimada += valor_estimado
        soma_homologada += valor_homologado
        soma_empenhada += total_empenhado_item

        itens.append(
            {
                "numero": item.get("numero_item"),
                "descricao": item.get("descricao") or "",
                "unidade": unidade,
                "quantidade_licitada": quantidade_licitada,
                "quantidade_homologada": quantidade_homologada,
                "quantidade_empenhada_estimada": (
                    quantidade_empenhada_item if possui_quantidade_empenhada else None
                ),
                "valor_unitario_estimado": _numero(item.get("valor_unitario_estimado")),
                "valor_total_estimado": valor_estimado,
                "valor_unitario_homologado": _numero(item.get("valor_unitario_homologado")),
                "valor_total_homologado": valor_homologado,
                "valor_empenhado": total_empenhado_item,
                "resultados": [
                    {
                        "fornecedor": resultado.get("nomeRazaoSocialFornecedor"),
                        "cnpj": resultado.get("niFornecedor"),
                        "quantidade": _numero(resultado.get("quantidadeHomologada")),
                        "valor_unitario": _numero(resultado.get("valorUnitarioHomologado")),
                        "valor_total": _numero(resultado.get("valorTotalHomologado")),
                    }
                    for resultado in resultados
                ],
                "empenhos": linhas_empenho,
                "candidatos_sem_item": item.get("empenhos_fornecedor_sem_item_identificado", []),
                "candidatos_fornecedor_divergente": item.get(
                    "empenhos_item_sem_fornecedor_compativel", []
                ),
                "status": item.get("status"),
            }
        )

    empenhos_sem_vinculo = []
    for registro in dados.get("empenhos", []):
        numero = registro.get("numeroContratoEmpenho")
        if numero in registros_vinculados:
            continue
        detalhe = registro.get("detalhesPortalTransparencia", {})
        detalhamento = detalhe.get("detalhamento", {})
        empenhos_sem_vinculo.append(
            {
                "numero": numero,
                "tipo": (registro.get("tipoContrato") or {}).get("nome") or "Registro",
                "data": detalhamento.get("data") or registro.get("dataAssinatura"),
                "fornecedor": detalhamento.get("nomeFavorecido")
                or registro.get("nomeRazaoSocialFornecedor"),
                "valor": _numero(detalhamento.get("valor") or registro.get("valorGlobal")),
                "status": detalhe.get("status") or "nao_mapeado",
                "mensagem": detalhe.get("mensagem") or detalhe.get("motivo") or "",
            }
        )

    itens.sort(key=lambda linha: (int(linha["numero"]) if str(linha["numero"]).isdigit() else 0))
    empenhos_sem_vinculo.sort(key=lambda linha: str(linha.get("numero") or ""))

    return {
        "status": dados.get("status"),
        "mensagem": dados.get("mensagem"),
        "chaves": dados.get("chaves_integracao", {}),
        "quantidade_registros": dados.get("quantidade_empenhos", 0),
        "quantidade_empenhos_detalhados": dados.get("quantidade_empenhos_com_detalhes", 0),
        "quantidade_itens": len(itens),
        "valor_estimado": soma_estimada,
        "valor_homologado": soma_homologada,
        "valor_empenhado_mapeado": soma_empenhada,
        "itens": itens,
        "registros_sem_vinculo": empenhos_sem_vinculo,
        "gerado_em": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M"),
    }


_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório consolidado da compra</title>
<style>
:root{--ink:#172b4d;--muted:#60718a;--blue:#174ea6;--teal:#087e75;--line:#dce4ef;--bg:#f4f7fb;--white:#fff;--amber:#9a5b00;--red:#a12a26}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Segoe UI",Arial,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:28px 22px 50px}.hero{background:linear-gradient(115deg,#103c78,#176b76);color:white;border-radius:16px;padding:28px 32px;box-shadow:0 10px 24px #153d6d25}
.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:11px;opacity:.8}.hero h1{margin:6px 0 8px;font-size:clamp(24px,3vw,34px);line-height:1.2}.hero p{margin:0;max-width:980px;color:#e3efff}.meta{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:18px;font-size:12px;color:#eaf3ff}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0}.card,.panel{background:var(--white);border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 8px #18345608}.card{padding:16px 18px}.card .label{font-size:12px;color:var(--muted)}.card .value{font-size:22px;font-weight:700;margin:4px 0}.card .sub{font-size:11px;color:var(--muted)}
.panel{padding:18px;margin:16px 0}.panel h2{margin:0 0 12px;font-size:18px}.note{border-left:4px solid #e6a23c;background:#fff8e9;padding:12px 14px;border-radius:4px;color:#614819;margin:14px 0}
.status-filters{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.status-filters button{border:1px solid var(--line);border-radius:20px;background:white;color:var(--ink);padding:7px 12px;font:inherit;font-size:12px;cursor:pointer}.status-filters button[aria-pressed="true"]{background:var(--blue);border-color:var(--blue);color:white}.status-filters button:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.toolbar{display:flex;gap:12px;align-items:center;margin:10px 0 14px;flex-wrap:wrap}.toolbar input{flex:1;min-width:220px;padding:10px 12px;border:1px solid #c9d4e2;border-radius:8px;font:inherit}.count{color:var(--muted);font-size:12px}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:9px}table{border-collapse:collapse;width:100%;min-width:1120px;background:white}th{position:sticky;top:0;background:#edf3fa;color:#314963;text-align:right;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:11px 10px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;user-select:none}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}th:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}th[aria-sort="ascending"]::after{content:" ▲";color:var(--blue)}th[aria-sort="descending"]::after{content:" ▼";color:var(--blue)}td{padding:10px;border-bottom:1px solid #e9eef4;text-align:right;vertical-align:top}tr.item-row{cursor:pointer}tr.item-row:hover{background:#f7fbff}.item-name{font-weight:600;min-width:230px}.item-name small{display:block;color:var(--muted);font-weight:400;margin-top:3px}.num{font-variant-numeric:tabular-nums;white-space:nowrap}.detail-row{display:none;background:#f8fafc}.detail-row.open{display:table-row}.detail-cell{text-align:left!important;padding:16px 20px!important}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.detail-box{border:1px solid var(--line);background:white;border-radius:8px;padding:12px}.detail-box h3{margin:0 0 8px;font-size:13px}.detail-box p{margin:4px 0}.detail-table{min-width:600px;font-size:12px}.detail-table th,.detail-table td{text-align:left;padding:7px}.badge{display:inline-block;border-radius:20px;padding:2px 8px;background:#e6f4f1;color:#12695e;font-size:11px}.badge.pending{background:#fff0d6;color:var(--amber)}.badge.no{background:#fbe9e8;color:var(--red)}.bar{height:5px;background:#e7edf5;border-radius:5px;margin-top:5px;overflow:hidden}.bar span{display:block;height:100%;background:var(--teal)}
.foot{color:var(--muted);font-size:11px;margin:16px 2px}.empty{text-align:center;color:var(--muted);padding:26px}.source-list{display:flex;gap:8px;flex-wrap:wrap}.source-list span{background:#edf3fa;border-radius:5px;padding:4px 8px;font-size:11px}
@media(max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.detail-grid{grid-template-columns:1fr}}
@media(max-width:520px){.wrap{padding:14px 10px 30px}.hero{padding:21px 18px}.cards{grid-template-columns:1fr 1fr;gap:8px}.card{padding:12px}.card .value{font-size:17px}.panel{padding:12px}.meta{display:grid;gap:4px}}
@media print{body{background:white}.wrap{max-width:none;padding:0}.hero{box-shadow:none;border-radius:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}.card,.panel{box-shadow:none;break-inside:avoid}.toolbar{display:none}table{min-width:0;font-size:10px}th,td{padding:5px}.detail-row{display:table-row!important}.item-row{break-after:avoid}.panel{margin:9px 0}}
</style>
</head>
<body>
<main class="wrap">
  <header class="hero">
    <div class="eyebrow">Compras públicas · Relatório de execução</div>
    <h1 id="title">Relatório da contratação</h1>
    <p id="object"></p>
    <div class="meta"><span id="pncp"></span><span id="org"></span><span id="generated"></span></div>
  </header>
  <section class="cards" id="cards"></section>
  <div class="note"><strong>Como interpretar:</strong> “Quantidade empenhada (estimada)” é calculada dividindo o valor das linhas de empenho pelo preço unitário homologado. A API publica o valor da linha, mas não a quantidade física empenhada; por isso, a quantidade é uma estimativa. Só são somadas linhas em que o número do item e o CNPJ do fornecedor correspondem ao resultado homologado. Valores/quantidades sem correspondência ficam separados como pendentes.</div>
  <section class="panel">
    <h2>Itens da contratação</h2>
    <div class="status-filters" role="group" aria-label="Filtrar itens por situação de empenho">
      <button type="button" data-item-filter="todos" aria-pressed="true">Todos</button>
      <button type="button" data-item-filter="deserto" aria-pressed="false">Desertos</button>
      <button type="button" data-item-filter="empenhado" aria-pressed="false">Empenhados</button>
      <button type="button" data-item-filter="nao_empenhado" aria-pressed="false">Não empenhados</button>
    </div>
    <div class="toolbar"><input id="search" type="search" placeholder="Filtrar por item, descrição, fornecedor ou empenho…" aria-label="Filtrar itens"><span class="count" id="count"></span></div>
    <div class="table-wrap"><table id="items-table"><thead><tr>
      <th>Item</th><th>Descrição / unidade</th><th>Qtd. licitada</th><th>Qtd. homologada</th><th>Qtd. empenhada*</th><th>Estimado</th><th>Homologado</th><th>Empenhado mapeado</th><th>Execução</th>
    </tr></thead><tbody id="items"></tbody></table></div>
    <p class="foot">Clique em uma linha para abrir fornecedores e empenhos. Quantidades de unidades diferentes não são somadas em um único total.</p>
  </section>
  <section class="panel" id="pending-panel">
    <h2>Registros sem vínculo confirmado a item</h2>
    <p class="foot">Estes registros fazem parte do total PNCP, mas não foram incluídos nos valores empenhados por item.</p>
    <div class="table-wrap"><table class="detail-table"><thead><tr><th>Registro</th><th>Tipo</th><th>Data</th><th>Fornecedor</th><th>Valor</th><th>Situação</th></tr></thead><tbody id="pending"></tbody></table></div>
  </section>
  <section class="panel">
    <h2>Fontes e critérios</h2>
    <div class="source-list"><span>PNCP — dados do edital e aba Contratos/Empenhos</span><span>Portal da Transparência — detalhes e itens das notas de empenho</span></div>
    <p class="foot">Valores empenhados por item são calculados a partir das linhas do documento de despesa. O valor consolidado por item conta somente correspondências de número do item e fornecedor homologado. Registros que não puderam ser vinculados aparecem na seção própria, sem serem contados duas vezes.</p>
  </section>
</main>
<script id="report-data" type="application/json">__REPORT_DATA__</script>
<script>
const D=JSON.parse(document.getElementById('report-data').textContent);
const fmtMoney=n=>n==null?'—':new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(n);
const fmtQty=n=>n==null?'—':new Intl.NumberFormat('pt-BR',{maximumFractionDigits:3}).format(n);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=n=>Number.isFinite(Number(n))?Number(n):0;
const pct=(a,b)=>b>0?Math.min(100,(a/b)*100):0;
const itemStatus=i=>number(i.valor_total_homologado)===0?'deserto':pct(number(i.valor_empenhado),number(i.valor_total_homologado))>0?'empenhado':'nao_empenhado';
function sortableValue(text){
 const value=text.trim().replace(/\s+/g,' ');
 if(!value||value==='—')return {type:'empty',value:''};
 const date=value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
 if(date)return {type:'number',value:Number(`${date[3]}${date[2]}${date[1]}`)};
 const isoDate=value.match(/^(\d{4})-(\d{2})-(\d{2})/);
 if(isoDate)return {type:'number',value:Number(`${isoDate[1]}${isoDate[2]}${isoDate[3]}`)};
 const numeric=value.replace(/R\$/g,'').replace(/%/g,'').replace(/\s/g,'');
 if(/^[+-]?\d[\d.,]*$/.test(numeric)){
  const normalized=numeric.includes(',')?numeric.replace(/\./g,'').replace(',','.'):numeric;
  const parsed=Number(normalized);
  if(Number.isFinite(parsed))return {type:'number',value:parsed};
 }
 return {type:'text',value};
}
function compareRows(a,b,column,direction){
 const leftCell=a.cells[column],rightCell=b.cells[column];
 const left=sortableValue(leftCell?.dataset.sortValue??leftCell?.innerText??'');
 const right=sortableValue(rightCell?.dataset.sortValue??rightCell?.innerText??'');
 let result;
 if(left.type==='empty'||right.type==='empty')return left.type===right.type?0:left.type==='empty'?1:-1;
 else if(left.type==='number'&&right.type==='number')result=left.value-right.value;
 else result=String(left.value).localeCompare(String(right.value),'pt-BR',{numeric:true,sensitivity:'base'});
 return result*direction;
}
function sortTable(table,column){
 const body=table.tBodies[0];
 if(!body)return;
 const previous=Number(table.dataset.sortColumn);
 const direction=previous===column&&table.dataset.sortDirection==='ascending'?-1:1;
 table.dataset.sortColumn=String(column);
 table.dataset.sortDirection=direction===1?'ascending':'descending';
 Array.from(table.tHead?.rows[0]?.cells||[]).forEach((header,index)=>{
  header.setAttribute('aria-sort',index===column?table.dataset.sortDirection:'none');
  header.title=`Ordenar por ${header.innerText.trim()}`;
 });
 if(table.id==='items-table'){
  const pairs=[];
  for(let index=0;index<body.rows.length;index++){
   const row=body.rows[index];
   if(!row.classList.contains('item-row'))continue;
   pairs.push([row,row.nextElementSibling]);
  }
  pairs.sort((a,b)=>compareRows(a[0],b[0],column,direction));
  pairs.forEach(pair=>pair.forEach(row=>row&&body.appendChild(row)));
  return;
 }
 Array.from(body.rows)
  .sort((a,b)=>compareRows(a,b,column,direction))
  .forEach(row=>body.appendChild(row));
}
document.addEventListener('click',event=>{
 const header=event.target.closest('th');
 const table=header?.closest('table');
 if(header&&table)sortTable(table,header.cellIndex);
});
document.addEventListener('keydown',event=>{
 if((event.key==='Enter'||event.key===' ')&&event.target.matches('th')){
  event.preventDefault();
  const header=event.target;
  const table=header.closest('table');
  if(table)sortTable(table,header.cellIndex);
 }
});
function prepareSortableHeaders(){
 document.querySelectorAll('thead th').forEach(header=>{
  header.tabIndex=0;
  header.setAttribute('role','button');
  if(!header.hasAttribute('aria-sort'))header.setAttribute('aria-sort','none');
  header.title=`Ordenar por ${header.innerText.trim()}`;
 });
}
document.getElementById('title').textContent=`Edital nº ${D.chaves.numero_compra||''}/${D.chaves.ano_compra||''}`;
document.getElementById('object').textContent=D.objeto||'Relatório consolidado dos itens e empenhos publicados.';
document.getElementById('pncp').textContent=`Controle PNCP: ${D.chaves.numero_controle_pncp||'—'}`;
document.getElementById('org').textContent=`Unidade: ${D.chaves.uasg_codigo||'—'} ${D.chaves.uasg_nome||''} · CNPJ: ${D.chaves.cnpj_orgao||'—'}`;
document.getElementById('generated').textContent=`Gerado em ${D.gerado_em}`;
const committed=D.valor_empenhado_mapeado||0;
const statusCounts=D.itens.reduce((counts,item)=>{counts[itemStatus(item)]++;return counts;},{deserto:0,empenhado:0,nao_empenhado:0});
const cards=[
 ['Itens',''+D.quantidade_itens,'Itens publicados no edital'],
 ['Valor estimado',fmtMoney(D.valor_estimado),'Soma dos valores estimados por item'],
 ['Valor homologado',fmtMoney(D.valor_homologado),'Soma dos resultados homologados'],
 ['Empenhado mapeado',fmtMoney(committed),`${D.quantidade_empenhos_detalhados} de ${D.quantidade_registros} registros com detalhamento`],
 ['Itens desertos',fmtQty(statusCounts.deserto),'Valor homologado igual a R$ 0,00'],
 ['Itens empenhados',fmtQty(statusCounts.empenhado),'Execução acima de 0%'],
 ['Itens não empenhados',fmtQty(statusCounts.nao_empenhado),'Execução igual a 0%, excluídos desertos']
];
document.getElementById('cards').innerHTML=cards.map(c=>`<div class="card"><div class="label">${esc(c[0])}</div><div class="value">${esc(c[1])}</div><div class="sub">${esc(c[2])}</div></div>`).join('');
const tbody=document.getElementById('items');
let selectedItemFilter='todos';
function detailHtml(i){
 const suppliers=(i.resultados||[]).map(r=>`<div class="detail-box"><h3>${esc(r.fornecedor||'Fornecedor não informado')}</h3><p>CNPJ: ${esc(r.cnpj||'—')}</p><p>Quantidade homologada: ${fmtQty(r.quantidade)} ${esc(i.unidade)}</p><p>Preço unitário: ${fmtMoney(r.valor_unitario)} · Total: ${fmtMoney(r.valor_total)}</p></div>`).join('')||'<div class="detail-box">Sem resultado homologado publicado.</div>';
 const emps=(i.empenhos||[]).map(e=>`<tr><td>${esc(e.numero)}</td><td>${esc(e.data||'—')}</td><td>${esc(e.fornecedor||'—')}</td><td data-sort-value="${esc(e.valor)}">${fmtMoney(e.valor)}</td><td data-sort-value="${esc(e.quantidade_estimada)}">${fmtQty(e.quantidade_estimada)} ${esc(i.unidade)}</td><td>${esc(e.descricao||'—')}</td><td>${e.codigo_documento?`<a href="https://portaldatransparencia.gov.br/despesas/empenho/${encodeURIComponent(e.codigo_documento)}" target="_blank" rel="noopener noreferrer">Abrir</a>`:'—'}</td></tr>`).join('');
 const candidates=[...(i.candidatos_sem_item||[]),...(i.candidatos_fornecedor_divergente||[])];
 return `<div class="detail-grid"><div><h3>Resultado(s) homologado(s)</h3>${suppliers}</div><div><h3>Empenhos vinculados ao item</h3>${emps?`<div class="table-wrap"><table class="detail-table"><thead><tr><th>Empenho</th><th>Emissão</th><th>Fornecedor</th><th>Valor da linha</th><th>Qtd. estimada</th><th>Descrição do item no empenho</th><th>Portal</th></tr></thead><tbody>${emps}</tbody></table></div>`:'<div class="detail-box">Nenhum empenho com item e fornecedor compatíveis.</div>'}</div></div>${candidates.length?`<div class="note"><strong>Não contabilizados:</strong> ${candidates.map(x=>esc(x.numero_empenho)).join(', ')} — sem correspondência suficiente para este item.</div>`:''}`;
}
function render(filter=document.getElementById('search').value){
 const itemsTable=document.getElementById('items-table');
 delete itemsTable.dataset.sortColumn;
 delete itemsTable.dataset.sortDirection;
 itemsTable.querySelectorAll('thead th').forEach(header=>header.setAttribute('aria-sort','none'));
 const q=filter.trim().toLocaleLowerCase('pt-BR');
 const rows=D.itens.filter(i=>(selectedItemFilter==='todos'||itemStatus(i)===selectedItemFilter)&&(!q||[i.numero,i.descricao,i.unidade,...(i.resultados||[]).flatMap(r=>[r.fornecedor,r.cnpj]),...(i.empenhos||[]).map(e=>e.numero)].join(' ').toLocaleLowerCase('pt-BR').includes(q)));
 document.getElementById('count').textContent=`${rows.length} de ${D.itens.length} itens`;
 tbody.innerHTML=rows.map((i,n)=>{
  const detail=`detail-${n}`, ratio=pct(number(i.valor_empenhado),number(i.valor_total_homologado));
  const status={deserto:'Deserto',empenhado:'Empenhado',nao_empenhado:'Não empenhado'}[itemStatus(i)];
  return `<tr class="item-row" data-detail="${detail}" data-item-status="${itemStatus(i)}"><td class="num" data-sort-value="${esc(i.numero)}">${esc(i.numero)}</td><td class="item-name" data-sort-value="${esc(i.descricao)}">${esc(i.descricao)}<small>${esc(i.unidade||'Unidade não informada')} · ${status}</small></td><td class="num" data-sort-value="${esc(i.quantidade_licitada)}">${fmtQty(i.quantidade_licitada)}</td><td class="num" data-sort-value="${esc(i.quantidade_homologada)}">${fmtQty(i.quantidade_homologada)}</td><td class="num" data-sort-value="${esc(i.quantidade_empenhada_estimada)}">${fmtQty(i.quantidade_empenhada_estimada)}</td><td class="num" data-sort-value="${esc(i.valor_total_estimado)}">${fmtMoney(i.valor_total_estimado)}</td><td class="num" data-sort-value="${esc(i.valor_total_homologado)}">${fmtMoney(i.valor_total_homologado)}</td><td class="num" data-sort-value="${esc(i.valor_empenhado)}">${fmtMoney(i.valor_empenhado)}<div class="bar"><span style="width:${ratio}%"></span></div></td><td class="num" data-sort-value="${i.valor_total_homologado?ratio:''}">${i.valor_total_homologado?fmtQty(ratio)+'%':'—'}</td></tr><tr class="detail-row" id="${detail}"><td colspan="9" class="detail-cell">${detailHtml(i)}</td></tr>`;
 }).join('')||'<tr><td colspan="9" class="empty">Nenhum item corresponde ao filtro.</td></tr>';
 tbody.querySelectorAll('.item-row').forEach(row=>row.addEventListener('click',()=>document.getElementById(row.dataset.detail).classList.toggle('open')));
 prepareSortableHeaders();
}
render();
document.getElementById('search').addEventListener('input',e=>render(e.target.value));
document.querySelectorAll('[data-item-filter]').forEach(button=>button.addEventListener('click',()=>{
 selectedItemFilter=button.dataset.itemFilter;
 document.querySelectorAll('[data-item-filter]').forEach(option=>option.setAttribute('aria-pressed',String(option===button)));
 render();
}));
const pending=document.getElementById('pending');
pending.innerHTML=D.registros_sem_vinculo.map(r=>`<tr><td>${esc(r.numero||'—')}</td><td>${esc(r.tipo)}</td><td>${esc(r.data||'—')}</td><td>${esc(r.fornecedor||'—')}</td><td data-sort-value="${esc(r.valor)}">${fmtMoney(r.valor)}</td><td><span class="badge ${r.status==='ok'?'':'pending'}">${esc(r.status)}${r.mensagem?': '+esc(r.mensagem):''}</span></td></tr>`).join('')||'<tr><td colspan="6" class="empty">Todos os registros foram vinculados a itens.</td></tr>';
prepareSortableHeaders();
</script>
</body>
</html>"""


def gerar_relatorio_html(dados: Dict[str, Any], caminho_saida: Path) -> Path:
    """Gera um relatório HTML autônomo, sem arquivos ou bibliotecas externas."""
    relatorio = _preparar_relatorio(dados)
    relatorio["objeto"] = dados.get("objeto")
    conteudo_json = json.dumps(relatorio, ensure_ascii=False, separators=(",", ":"))
    conteudo_json = conteudo_json.replace("</", "<\\/")
    html = _HTML.replace("__REPORT_DATA__", conteudo_json)
    caminho_saida = Path(caminho_saida)
    caminho_saida.write_text(html, encoding="utf-8")
    return caminho_saida
