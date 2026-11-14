from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

_BRAZIL_TIMEZONE = timezone(timedelta(hours=-3))

_PISO_POR_ETAPA = {
    "coleta": 0.05,
    "empenhos": 0.45,
    "relatorio": 0.90,
    "concluido": 1.0,
}

_PADRAO_PAGINA = re.compile(r"consultando p[áa]gina (\d+) de itens", re.IGNORECASE)
_PADRAO_PAGINA_CONCLUIDA = re.compile(
    r"p[áa]gina (\d+) conclu[íi]da: (\d+) itens coletados", re.IGNORECASE
)
_PADRAO_PNCP = re.compile(r"registros do pncp recebidos: (\d+)", re.IGNORECASE)
_PADRAO_PORTAL = re.compile(
    r"portal da transpar[êe]ncia retornou (\d+) empenho", re.IGNORECASE
)
_PADRAO_MAPEAMENTO = re.compile(r"mapeamento conclu[íi]do: (\d+) empenhos", re.IGNORECASE)
_PADRAO_PROCESSO = re.compile(r"atualizando processo (\d+)/(\d+)", re.IGNORECASE)


class ProgressoTracker:
    """Traduz mensagens de progresso em etapa, percentual e previsão de conclusão."""

    def __init__(
        self,
        acao: str = "one",
        duracao_referencia: Optional[float] = None,
        iniciado_em: Optional[datetime] = None,
    ) -> None:
        self.acao = acao
        self.iniciado_em = iniciado_em or datetime.now().astimezone()
        self.duracao_referencia = (
            float(duracao_referencia) if duracao_referencia and duracao_referencia > 0 else None
        )
        self.etapa = "coleta"
        self.mensagem = "Preparando a atualização."
        self.percentual = 0.0
        self.estatisticas: Dict[str, Any] = {
            "paginas_coletadas": 0,
            "itens_coletados": 0,
            "empenhos_pncp": None,
            "empenhos_portal": None,
            "processo_indice": None,
            "processos_total": None,
        }

    def _decorrido(self, agora: Optional[datetime] = None) -> float:
        agora = agora or datetime.now().astimezone()
        return max(0.0, (agora - self.iniciado_em).total_seconds())

    def _percentual_por_tempo(self, decorrido: float) -> float:
        if not self.duracao_referencia:
            return 0.0
        return min(0.97, decorrido / self.duracao_referencia)

    def atualizar(self, mensagem: str, agora: Optional[datetime] = None) -> Dict[str, Any]:
        self.mensagem = mensagem
        texto = mensagem or ""

        if _PADRAO_PROCESSO.search(texto):
            indice, total = _PADRAO_PROCESSO.search(texto).groups()
            self.estatisticas["processo_indice"] = int(indice)
            self.estatisticas["processos_total"] = int(total)

        if _PADRAO_PAGINA.search(texto):
            self.etapa = "coleta"
        if _PADRAO_PAGINA_CONCLUIDA.search(texto):
            pagina, itens = _PADRAO_PAGINA_CONCLUIDA.search(texto).groups()
            self.estatisticas["paginas_coletadas"] = int(pagina)
            self.estatisticas["itens_coletados"] = int(itens)
            self.etapa = "coleta"
        elif "reutilizando itens" in texto.lower():
            self.etapa = "coleta"

        achado_pncp = _PADRAO_PNCP.search(texto)
        if achado_pncp:
            self.estatisticas["empenhos_pncp"] = int(achado_pncp.group(1))
            self.etapa = "empenhos"
        if "consultando e mapeando" in texto.lower():
            self.etapa = "empenhos"
        if "buscando empenhos no portal" in texto.lower():
            self.etapa = "empenhos"

        achado_portal = _PADRAO_PORTAL.search(texto)
        if achado_portal:
            self.estatisticas["empenhos_portal"] = int(achado_portal.group(1))
            self.etapa = "empenhos"

        achado_mapeamento = _PADRAO_MAPEAMENTO.search(texto)
        if achado_mapeamento:
            self.estatisticas["empenhos_mapeados"] = int(achado_mapeamento.group(1))
            self.etapa = "empenhos"

        if "gerando os arquivos html" in texto.lower():
            self.etapa = "relatorio"
        if "relatório individual e índice atualizados" in texto.lower():
            self.etapa = "concluido"

        decorrido = self._decorrido(agora)
        percentual = max(
            self._percentual_por_tempo(decorrido),
            _PISO_POR_ETAPA.get(self.etapa, 0.0),
        )
        self.percentual = min(0.99 if self.etapa != "concluido" else 1.0, percentual)
        return self.estado(agora)

    def concluir(self, sucesso: bool = True, agora: Optional[datetime] = None) -> Dict[str, Any]:
        self.etapa = "concluido" if sucesso else "erro"
        self.percentual = 1.0 if sucesso else self.percentual
        return self.estado(agora)

    def estado(self, agora: Optional[datetime] = None) -> Dict[str, Any]:
        agora = agora or datetime.now().astimezone()
        decorrido = self._decorrido(agora)
        restante: Optional[float] = None
        previsao: Optional[str] = None
        if self.etapa == "concluido":
            restante = 0.0
            previsao = agora.astimezone(_BRAZIL_TIMEZONE).isoformat(timespec="seconds")
        elif self.etapa == "erro":
            restante = None
        elif self.duracao_referencia:
            restante = max(0.0, self.duracao_referencia - decorrido)
            previsao = (
                self.iniciado_em + timedelta(seconds=self.duracao_referencia)
            ).astimezone(_BRAZIL_TIMEZONE).isoformat(timespec="seconds")
        elif self.percentual >= 0.08:
            restante = decorrido * (1 - self.percentual) / self.percentual
            previsao = (agora + timedelta(seconds=restante)).astimezone(
                _BRAZIL_TIMEZONE
            ).isoformat(timespec="seconds")

        return {
            "etapa": self.etapa,
            "percentual": round(self.percentual * 100, 1),
            "mensagem": self.mensagem,
            "segundos_decorridos": round(decorrido, 1),
            "segundos_restantes": round(restante, 0) if restante is not None else None,
            "previsao_conclusao": previsao,
            "duracao_referencia_segundos": self.duracao_referencia,
            "estatisticas": dict(self.estatisticas),
        }
