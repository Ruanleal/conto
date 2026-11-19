package com.conto.notificacoes;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * As regras do leitor, sem nada do Android (dá para testar num computador): quais notificações interessam, quando uma
 * é repetida e como a lista guardada muda. O Armazem só lê e grava o texto JSON nas SharedPreferences.
 */
final class Regras {

  static final int MAXIMO = 300;
  static final long JANELA_REPETIDA_MS = 10 * 60 * 1000L;   // a mesma notificação de novo em 10 min = repetida

  private Regras() {
  }

  /** Apps de conversa e e-mail: mensagens de pessoas com "R$" não são movimentações do banco (e são privadas). */
  static final String IGNORADOS_PADRAO = "com.whatsapp,com.whatsapp.w4b,org.telegram.messenger,com.instagram.android,"
      + "com.facebook.orca,com.facebook.katana,com.google.android.gm,com.microsoft.office.outlook,com.discord,"
      + "com.snapchat.android,com.twitter.android,com.zhiliaoapp.musically,com.linkedin.android";

  static boolean naLista(String lista, String app) {
    if (lista == null) {
      return false;
    }
    for (String p : lista.split(",")) {
      if (p.trim().length() > 0 && p.trim().equalsIgnoreCase(app)) {
        return true;
      }
    }
    return false;
  }

  /** Monitorados vazio = todos os apps; um app ignorado nunca entra. */
  static boolean monitorado(String monitorados, String ignorados, String app) {
    if (naLista(ignorados, app)) {
      return false;
    }
    return monitorados == null || monitorados.trim().length() == 0 || naLista(monitorados, app);
  }

  /** Tem cara de movimentação de dinheiro: "R$", "BRL" ou "reais" no título ou no texto. */
  static boolean temValor(String titulo, String texto) {
    String t = (" " + titulo + " " + texto + " ").toLowerCase();
    return t.contains("r$") || t.contains("brl") || t.contains(" reais");
  }

  static String id(String app, String titulo, String texto, long quando) {
    return quando + "-" + Integer.toHexString((app + "|" + titulo + "|" + texto).hashCode());
  }

  /**
   * Põe a notificação no fim da lista e devolve o id; null (lista intacta) quando é a mesma notificação de novo
   * (mesmo app, título e texto em menos de 10 min: os apps atualizam a mesma notificação várias vezes).
   * Passando de MAXIMO, as mais antigas saem.
   */
  static String guardar(JSONArray arr, String app, String titulo, String texto, long quando) throws Exception {
    for (int i = arr.length() - 1; i >= 0; i--) {
      JSONObject o = arr.optJSONObject(i);
      if (o != null && app.equals(o.optString("app")) && titulo.equals(o.optString("titulo"))
          && texto.equals(o.optString("texto")) && Math.abs(quando - o.optLong("quando")) < JANELA_REPETIDA_MS) {
        return null;
      }
    }
    String id = id(app, titulo, texto, quando);
    JSONObject o = new JSONObject();
    o.put("id", id);
    o.put("app", app);
    o.put("titulo", titulo);
    o.put("texto", texto);
    o.put("quando", quando);
    arr.put(o);
    while (arr.length() > MAXIMO) {
      arr.remove(0);
    }
    return id;
  }

  /** Quantos ids de notificacoes ja guardadas o leitor lembra (para nao guardar de novo ao reler a barra). */
  static final int MAX_VISTOS = 500;

  /** A notificacao com esse id ja foi guardada alguma vez (mesmo que ja tenha sido lancada ou ignorada)? */
  static boolean jaVisto(JSONArray vistos, String id) {
    for (int i = 0; i < vistos.length(); i++) {
      if (id.equals(vistos.optString(i))) {
        return true;
      }
    }
    return false;
  }

  /** Lembra o id (os mais antigos saem passando de MAX_VISTOS). */
  static void marcarVisto(JSONArray vistos, String id) {
    vistos.put(id);
    while (vistos.length() > MAX_VISTOS) {
      vistos.remove(0);
    }
  }

  /**
   * Por que uma notificacao foi (ou nao) guardada. Ordem das conferencias igual a do servico: do proprio app,
   * app ignorado/nao monitorado, resumo de grupo, sem texto, sem valor em dinheiro, ja guardada antes, repetida.
   */
  static final String GUARDADA = "guardada";
  static final String DO_APP = "do próprio Contô";
  static final String APP_FORA = "app ignorado";
  static final String RESUMO = "resumo de grupo";
  static final String VAZIA = "sem texto";
  static final String SEM_VALOR = "sem valor em R$";
  static final String JA_VISTA = "já guardada antes";
  static final String REPETIDA = "repetida";

  /**
   * O filtro do servico, na ordem: devolve o motivo para NAO guardar, ou null quando a notificacao interessa.
   * (Antes de guardar ainda valem "ja guardada antes" e "repetida", que dependem do que esta guardado.)
   */
  static String filtro(String app, String proprio, String monitorados, String ignorados, boolean resumoDeGrupo,
                       String titulo, String texto, boolean soComValor) {
    if (app == null || app.equals(proprio)) {
      return DO_APP;
    }
    if (!monitorado(monitorados, ignorados, app)) {
      return APP_FORA;
    }
    if (resumoDeGrupo) {
      return RESUMO;
    }
    if (titulo.length() == 0 && texto.length() == 0) {
      return VAZIA;
    }
    if (soComValor && !temValor(titulo, texto)) {
      return SEM_VALOR;
    }
    return null;
  }

  /** Texto do diagnostico mostrado no app. horario(ms) formata a hora; nomeApp(pacote) da o nome do app. */
  static String diagnostico(boolean acesso, boolean conectado, long vistas, String ultimoNome, String ultimoMotivo,
                            String ultimaHora) {
    StringBuilder s = new StringBuilder();
    if (!acesso) {
      s.append("Leitor desligado (acesso não liberado)");
    } else if (conectado) {
      s.append("Leitor ligado");
    } else {
      s.append("Leitor parado pelo Android: toque em Atualizar para religar");
    }
    s.append(" • ").append(vistas).append(vistas == 1 ? " notificação vista" : " notificações vistas");
    if (ultimoNome != null && ultimoNome.length() > 0) {
      s.append(" • última: ").append(ultimoNome).append(" às ").append(ultimaHora).append(" (").append(ultimoMotivo)
          .append(")");
    }
    return s.toString();
  }

  /**
   * Guarda se for nova: {motivo, id}. JA_VISTA quando aquela mesma notificacao (mesmo app, texto e horario) ja foi
   * guardada alguma vez -- ao religar, o leitor rele a barra, e o que ja foi lancado ou ignorado nao pode voltar;
   * REPETIDA quando e a mesma de novo em menos de 10 min; GUARDADA com o id novo.
   */
  static String[] guardarSeNova(JSONArray arr, JSONArray vistos, String app, String titulo, String texto, long quando)
      throws Exception {
    if (jaVisto(vistos, id(app, titulo, texto, quando))) {
      return new String[] {JA_VISTA, null};
    }
    String novo = guardar(arr, app, titulo, texto, quando);
    if (novo == null) {
      return new String[] {REPETIDA, null};
    }
    marcarVisto(vistos, novo);
    return new String[] {GUARDADA, novo};
  }

  /** Lista sem o item desse id (os outros na mesma ordem). */
  static JSONArray semId(JSONArray arr, String id) {
    JSONArray novo = new JSONArray();
    for (int i = 0; i < arr.length(); i++) {
      JSONObject o = arr.optJSONObject(i);
      if (o != null && !o.optString("id").equals(id)) {
        novo.put(o);
      }
    }
    return novo;
  }
}
