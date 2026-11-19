package com.conto.notificacoes;

import android.app.Notification;
import android.content.ComponentName;
import android.os.Build;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

/**
 * Serviço que o Android liga quando a pessoa libera o "Acesso a notificações" para o app.
 * Guarda as notificações dos apps monitorados no Armazem (SharedPreferences), mesmo com o app fechado.
 *
 * v2.0.1: alguns celulares (ex.: Xiaomi) derrubam o serviço quando o app vai para o fundo e o Android não o religa
 * sozinho. Ao ser ligado de novo (onListenerConnected) o serviço relê as notificações que ainda estão na barra; ao
 * ser desligado pelo sistema, pede para ser religado (requestRebind, Android 7+).
 */
public class ServicoNotificacoes extends NotificationListenerService {

  @Override
  public void onListenerConnected() {
    try {
      Armazem.conectado(this, true);
      StatusBarNotification[] ativas = getActiveNotifications();
      if (ativas != null) {
        for (StatusBarNotification sbn : ativas) {
          processar(sbn);
        }
      }
    } catch (Throwable t) {
      // ler a barra e um extra; nunca pode derrubar o servico
    }
  }

  @Override
  public void onListenerDisconnected() {
    try {
      Armazem.conectado(this, false);
      if (Build.VERSION.SDK_INT >= 24) {
        requestRebind(new ComponentName(this, ServicoNotificacoes.class));
      }
    } catch (Throwable t) {
      // sem religar: o app pede de novo ao abrir (LeitorNotificacoes.Reconectar)
    }
  }

  @Override
  public void onNotificationPosted(StatusBarNotification sbn) {
    try {
      processar(sbn);
    } catch (Throwable t) {
      // um serviço do sistema nunca pode derrubar o app por causa de uma notificação estranha
    }
  }

  private void processar(StatusBarNotification sbn) {
    if (sbn == null) {
      return;
    }
    String app = sbn.getPackageName();
    Notification n = sbn.getNotification();
    Bundle ex = n == null ? null : n.extras;
    String titulo = texto(ex, Notification.EXTRA_TITLE);
    String corpo = texto(ex, Notification.EXTRA_BIG_TEXT);
    if (corpo.length() == 0) {
      corpo = texto(ex, Notification.EXTRA_TEXT);
    }
    if (corpo.length() == 0 && n != null && n.tickerText != null) {
      corpo = n.tickerText.toString();
    }
    boolean resumo = n == null || (n.flags & Notification.FLAG_GROUP_SUMMARY) != 0;   // resumo de grupo repete as outras
    long quando = sbn.getPostTime();
    String motivo = Regras.filtro(app, getPackageName(), Armazem.monitorados(this), Armazem.ignorados(this), resumo,
        titulo, corpo, Armazem.soComValor(this));
    if (Regras.DO_APP.equals(motivo)) {
      return;                                   // as do proprio Contô nem contam no diagnostico
    }
    String id = null;
    if (motivo == null) {
      String[] r = Armazem.guardar(this, app, titulo, corpo, quando);
      motivo = r[0];
      id = r[1];
    }
    Armazem.anotar(this, app, motivo, quando);
    if (id != null) {
      LeitorNotificacoes ativo = Armazem.componenteAtivo;
      if (ativo != null) {
        ativo.avisar(id, app, titulo, corpo);
      }
    }
  }

  private static String texto(Bundle ex, String chave) {
    if (ex == null) {
      return "";
    }
    CharSequence cs = ex.getCharSequence(chave);
    return cs == null ? "" : cs.toString().trim();
  }
}
