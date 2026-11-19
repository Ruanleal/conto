package com.conto.notificacoes;

import org.json.JSONArray;

/** Roda as regras do leitor (Regras.java, o mesmo arquivo que vai na extensão) num computador. */
public class TesteRegras {
  static int ok = 0, falhas = 0;

  static void confere(boolean c, String o) {
    if (c) { ok++; } else { falhas++; System.out.println("FALHOU: " + o); }
  }

  public static void main(String[] a) throws Exception {
    // monitorado
    String ig = Regras.IGNORADOS_PADRAO;
    confere(Regras.monitorado("", ig, "com.nu.production"), "lista vazia = todos");
    confere(Regras.monitorado(null, ig, "x"), "lista nula = todos");
    confere(Regras.monitorado(" com.nu.production , com.itau", ig, "com.itau"), "na lista (com espacos)");
    confere(Regras.monitorado("com.nu.production", ig, "COM.NU.PRODUCTION"), "sem diferenca de maiuscula");
    confere(!Regras.monitorado("com.nu.production", ig, "com.itau"), "fora da lista");
    confere(!Regras.monitorado("", ig, "com.whatsapp"), "WhatsApp ignorado por padrao");
    confere(!Regras.monitorado("com.whatsapp", ig, "com.whatsapp"), "ignorado vence a lista de monitorados");
    confere(Regras.monitorado("", "", "com.whatsapp"), "sem ignorados: entra");
    confere(Regras.monitorado("", ig, "com.google.android.apps.messaging"), "SMS (app de mensagens do Android) entra");
    // temValor
    confere(Regras.temValor("Compra aprovada", "R$ 45,90 em MERCADO"), "R$");
    confere(Regras.temValor("Pix recebido", "Voce recebeu 100 reais"), "reais");
    confere(Regras.temValor("", "BRL 10.00 purchase"), "BRL");
    confere(Regras.temValor("r$10", ""), "r$ minusculo no titulo");
    confere(!Regras.temValor("Seu codigo", "Use 123456 para entrar"), "sem valor");
    confere(!Regras.temValor("Promo", "Ganhe surreais descontos"), "'surreais' nao e 'reais'");
    // guardar + repetida
    JSONArray arr = new JSONArray();
    String id1 = Regras.guardar(arr, "com.nu.production", "Compra aprovada", "R$ 10,00 em A", 1000000L);
    confere(id1 != null && arr.length() == 1, "guarda a primeira");
    confere(Regras.guardar(arr, "com.nu.production", "Compra aprovada", "R$ 10,00 em A", 1000000L + 9 * 60 * 1000L) == null
        && arr.length() == 1, "mesma em 9 min = repetida");
    confere(Regras.guardar(arr, "com.nu.production", "Compra aprovada", "R$ 10,00 em A", 1000000L + 10 * 60 * 1000L) != null
        && arr.length() == 2, "mesma depois de 10 min = nova (outra compra igual)");
    confere(Regras.guardar(arr, "com.itau", "Compra aprovada", "R$ 10,00 em A", 1000000L) != null && arr.length() == 3,
        "outro app = nova");
    confere(Regras.guardar(arr, "com.nu.production", "Compra aprovada", "R$ 10,01 em A", 1000000L) != null
        && arr.length() == 4, "outro texto = nova");
    confere(arr.getJSONObject(0).getString("id").equals(id1), "ordem: a mais antiga primeiro");
    // semId
    JSONArray menos = Regras.semId(arr, id1);
    confere(menos.length() == 3 && !menos.getJSONObject(0).getString("id").equals(id1), "remove so aquela");
    confere(Regras.semId(arr, "nao-existe").length() == 4, "id que nao existe nao muda nada");
    // maximo
    JSONArray grande = new JSONArray();
    for (int i = 0; i < Regras.MAXIMO + 25; i++) {
      Regras.guardar(grande, "app", "t", "R$ " + i, i * 1000L);
    }
    confere(grande.length() == Regras.MAXIMO, "no maximo " + Regras.MAXIMO);
    confere(Regras.MAXIMO == 300 && grande.length() == 300, "guarda as 300 mais novas (o que o relatorio promete)");
    confere(grande.getJSONObject(0).getString("texto").equals("R$ 25"), "as mais antigas saem");
    // id estavel
    confere(Regras.id("a", "b", "c", 5L).equals(Regras.id("a", "b", "c", 5L)), "id estavel");
    // v2.0.1: ja vistas (reler a barra ao religar o leitor nao traz de volta o que ja foi tratado)
    JSONArray pend = new JSONArray(), vistos = new JSONArray();
    String[] g1 = Regras.guardarSeNova(pend, vistos, "com.picpay", "Carla enviou um Pix para voce", "R$ 0,01", 5000000L);
    confere(Regras.GUARDADA.equals(g1[0]) && g1[1] != null && pend.length() == 1 && vistos.length() == 1, "nova: guardada e lembrada");
    String[] g2 = Regras.guardarSeNova(pend, vistos, "com.picpay", "Carla enviou um Pix para voce", "R$ 0,01", 5000000L);
    confere(Regras.JA_VISTA.equals(g2[0]) && g2[1] == null && pend.length() == 1, "a mesma relida da barra: ja vista");
    pend = Regras.semId(pend, g1[1]);
    String[] g3 = Regras.guardarSeNova(pend, vistos, "com.picpay", "Carla enviou um Pix para voce", "R$ 0,01", 5000000L);
    confere(Regras.JA_VISTA.equals(g3[0]) && pend.length() == 0, "ja lancada/ignorada e relida da barra: nao volta");
    String[] g4 = Regras.guardarSeNova(pend, vistos, "com.picpay", "Carla enviou um Pix para voce", "R$ 0,01", 5000000L + 60000L);
    confere(Regras.REPETIDA.equals(g4[0]) == false && Regras.GUARDADA.equals(g4[0]), "outro horario e ja tratada a anterior: nova (outro Pix igual)");
    String[] g5 = Regras.guardarSeNova(pend, vistos, "com.picpay", "Carla enviou um Pix para voce", "R$ 0,01", 5000000L + 120000L);
    confere(Regras.REPETIDA.equals(g5[0]) && g5[1] == null, "a mesma de novo em 1 min, ainda guardada: repetida");
    JSONArray vv = new JSONArray();
    for (int i = 0; i < Regras.MAX_VISTOS + 7; i++) {
      Regras.marcarVisto(vv, "id" + i);
    }
    confere(vv.length() == 500 && Regras.MAX_VISTOS == 500 && !Regras.jaVisto(vv, "id0") && Regras.jaVisto(vv, "id506"),
        "lembra as 500 mais novas");
    // filtro (motivo de nao guardar)
    confere(Regras.DO_APP.equals(Regras.filtro("com.conto", "com.conto", "", ig, false, "t", "R$ 1", true)), "do proprio app");
    confere(Regras.APP_FORA.equals(Regras.filtro("com.whatsapp", "com.conto", "", ig, false, "Ana", "te devo R$ 10", true)), "WhatsApp");
    confere(Regras.RESUMO.equals(Regras.filtro("com.nu.production", "com.conto", "", ig, true, "t", "R$ 1", true)), "resumo de grupo");
    confere(Regras.APP_FORA.equals(Regras.filtro("com.whatsapp", "com.conto", "", ig, true, "t", "R$ 1", true)),
        "app ignorado vem antes de resumo de grupo (o motivo certo no diagnostico)");
    confere(Regras.VAZIA.equals(Regras.filtro("com.nu.production", "com.conto", "", ig, false, "", "", true)), "sem texto");
    confere(Regras.SEM_VALOR.equals(Regras.filtro("com.nu.production", "com.conto", "", ig, false, "Fatura", "Sua fatura fechou", true)), "sem R$");
    confere(Regras.filtro("com.nu.production", "com.conto", "", ig, false, "Fatura", "Sua fatura fechou", false) == null, "sem R$ mas ApenasComValor desligado");
    confere(Regras.filtro("com.nu.production", "com.conto", "", ig, false, "Transferencia recebida",
        "Voce recebeu uma transferencia de R$ 67,84 de ENJOEI SA.", true) == null, "Nubank (caso relatado) interessa");
    confere(Regras.filtro(null, "com.conto", "", ig, false, "t", "R$ 1", true) != null, "sem pacote: fora");
    // diagnostico
    confere(Regras.diagnostico(true, true, 12, "Nubank", Regras.GUARDADA, "17/11 14:32")
        .equals("Leitor ligado • 12 notificações vistas • última: Nubank às 17/11 14:32 (guardada)"), "diagnostico ligado");
    confere(Regras.diagnostico(true, false, 1, "", "", "")
        .equals("Leitor parado pelo Android: toque em Atualizar para religar • 1 notificação vista"), "diagnostico parado");
    confere(Regras.diagnostico(false, false, 0, "", "", "").startsWith("Leitor desligado (acesso não liberado) • 0 notificações"),
        "diagnostico sem acesso");
    // casos de um arquivo (para comparar com o simulador): app|titulo|texto|quando|tratar por linha -> motivo|id
    if (a.length > 0) {
      JSONArray v = new JSONArray(), vis = new JSONArray();
      java.io.BufferedReader r = new java.io.BufferedReader(new java.io.InputStreamReader(new java.io.FileInputStream(a[0]), "UTF-8"));
      String l;
      StringBuilder sb = new StringBuilder();
      while ((l = r.readLine()) != null) {
        String[] p = l.split("\t", -1);
        String motivo = Regras.filtro(p[0], "appinventor.ai_conto.Conto", "", Regras.IGNORADOS_PADRAO, false, p[1], p[2], true);
        String id = null;
        if (motivo == null) {
          String[] g = Regras.guardarSeNova(v, vis, p[0], p[1], p[2], Long.parseLong(p[3]));
          motivo = g[0];
          id = g[1];
        }
        if (id != null && p.length > 4 && p[4].equals("1")) {
          v = Regras.semId(v, id);          // o app tratou (lancou ou ignorou)
        }
        sb.append(motivo).append('\t').append(id == null ? "null" : id).append('\n');
      }
      java.nio.file.Files.write(java.nio.file.Paths.get(a[1]), sb.toString().getBytes("UTF-8"));
    }
    System.out.println("TESTE DAS REGRAS DA EXTENSAO (Java): " + ok + " ok, " + falhas + " falhas");
    System.exit(falhas == 0 ? 0 : 1);
  }
}
